import logging
import threading
import time
from flask import Flask, Request, request, jsonify
import sqlite3
import uuid
import pika
import json
import requests
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)

# Initialize SQLite database
conn = sqlite3.connect('booking.db')
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS bookings
                  (id TEXT PRIMARY KEY, apartment_id TEXT, start_date TEXT, end_date TEXT, who TEXT)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS availableApartmentList
                  (id INTEGER PRIMARY KEY AUTOINCREMENT, apartment_id TEXT)''')

conn.commit()
conn.close()

# Initialize RabbitMQ connection... listen to events
def connect_to_rabbitmq():
    while True:
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters('rabbitmq'))
            channel = connection.channel()
            channel.queue_declare(queue='events')
            logging.debug('Connected to RabbitMQ')
            logging.debug(channel)  # Print the content of channel
            # Set up RabbitMQ event consumer
            time.sleep(5)
            channel.basic_consume(queue='events', on_message_callback=handle_rabbitmq_event, auto_ack=True)
            logging.debug('Added basic_consume')
            return connection, channel
        except pika.exceptions.ConnectionClosedByBroker:
            logging.error('Connection to RabbitMQ closed by broker. Retrying...')
        except Exception as e:
            logging.error('Error connecting to RabbitMQ: %s. Retrying...', str(e))
        
        time.sleep(5)  # Retry the connection every 5 seconds

def handle_rabbitmq_event(ch, method, properties, body):
    logging.debug('Received event from RabbitMQ')
    event = json.loads(body)
    logging.debug('Event: ')
    logging.debug(event)
    if event['type'] == 'apartment_added':
        ap_added(event['apartment_id'])
    elif event['type'] == 'apartment_removed':
        ap_removed(event['apartment_id'])

def run_rabbitmq_consumer():
    connection, channel = connect_to_rabbitmq()
    logging.debug('Starting consuming')
    channel.start_consuming()


# Function to be executed when an apartment is added
def ap_added(apartment_id):
    logging.error(f"Apartment {apartment_id} added.")
    conn = sqlite3.connect('booking.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM availableApartmentList WHERE apartment_id=?", (apartment_id,))
    existing_apartment = cursor.fetchone()
    
    if not existing_apartment:
        cursor.execute("INSERT INTO availableApartmentList (apartment_id) VALUES (?)", (apartment_id,))
        conn.commit()
        logging.debug(f"Appartment {apartment_id} added to availableApartmentList")
    
    conn.close()

# Function to be executed when an apartment is removed
def ap_removed(apartment_id):
    conn = sqlite3.connect('booking.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM availableApartmentList WHERE apartment_id=?", (apartment_id,))
    existing_apartment = cursor.fetchone()
    
    if existing_apartment:
        cursor.execute("DELETE FROM availableApartmentList WHERE apartment_id=?", (apartment_id,))
        conn.commit()
        logging.debug(f"Appartment {apartment_id} removed from availableApartmentList")
    
    conn.close()



#####SEND MESSAGE TO RABBITMQ#####
def sendMessageToRabbitMQ(message):
    try:
        connection = pika.BlockingConnection(pika.ConnectionParameters('rabbitmq'))
        logging.debug('ConnectToRabbit')
        try:
            channel = connection.channel()
            channel.queue_declare(queue='bookingEvents')
            channel.basic_publish(exchange='', routing_key='bookingEvents', body=message)
        except Exception as e:
            logging.error("Error in RabbitMQ channel setup: %s", str(e))
        finally:
            connection.close()
    except Exception as e:
        logging.error("Error connecting to RabbitMQ: %s", str(e))    


####INIT APPARTMENT ######
def initialize_apartments():
    max_retries = 10  
    retry_delay = 20  
    retry_count = 0

    while retry_count < max_retries:
        try:
            response = requests.get('http://apartment:5000/list', timeout=5)
            response.raise_for_status()  
            if response.status_code == 200:
                available_apartments = response.json().get('apartments', [])
                for apartment in available_apartments:
                    apartment_id = apartment[0]
                    if apartment_id:
                        ap_added(apartment_id)
            else:
                print(f"Error fetching available apartments: {response.status_code}")  
            break  
        except requests.exceptions.RequestException as e:
            retry_count += 1
            logging.error('Error making HTTP request to booking service: %s. Retrying (Attempt %d/%d)...', str(e), retry_count, max_retries)
    
        time.sleep(retry_delay) 
    if retry_count == max_retries:
        logging.error('Failed to make HTTP request after %d attempts.', max_retries)

##############################################################################
# API to add a booking
@app.route('/add', methods=['POST'])
def add_booking():
    data = request.get_json()
    booking_id = str(uuid.uuid4())
    apartment_id = data['apartment_id']
    start_date = data['start_date']
    end_date = data['end_date']
    who = data['who']

    # Check if the apartment is in the available list
    if not is_apartment_in_available_list(apartment_id):
        return jsonify({"message": "Apartment not available for booking"})
    
    # Check if the apartment is available
    if is_booking_conflict(apartment_id, start_date, end_date):
        return jsonify({"message": "Apartment not available during the specified dates"})

    conn = sqlite3.connect('booking.db')
    cursor = conn.cursor()
    cursor.execute("INSERT INTO bookings VALUES (?, ?, ?, ?, ?)",
                   (booking_id, apartment_id, start_date, end_date, who))
    conn.commit()
    conn.close()
    event = {
        'type': 'booking_added',
        'booking_id': booking_id,
        'apartment_id': apartment_id,
        'start_date': start_date,
        'end_date': end_date,
        'who': who
    }
    sendMessageToRabbitMQ(json.dumps(event))
    return jsonify({"message": "Booking added successfully", "id": booking_id})

# API to cancel a booking
@app.route('/cancel', methods=['DELETE'])
def cancel_booking():
    booking_id = request.args.get('id')

    conn = sqlite3.connect('booking.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM bookings WHERE id=?", (booking_id,))
    conn.commit()
    conn.close()
    event = {
        'type': 'booking_canceled',
        'booking_id': booking_id
    }
    sendMessageToRabbitMQ(json.dumps(event))
    return jsonify({"message": "Booking canceled successfully"})

# API to change booking dates
@app.route('/change', methods=['PUT'])
def change_booking():
    data = request.get_json()
    booking_id = data['id']
    start_date = data['start_date']
    end_date = data['end_date']

    # Check if the apartment is available for the new dates
    old_booking = get_booking_by_id(booking_id)
    if is_booking_conflict(old_booking['apartment_id'], start_date, end_date):
        return jsonify({"message": "Apartment not available during the specified dates"})

    conn = sqlite3.connect('booking.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE bookings SET start_date=?, end_date=? WHERE id=?",
                   (start_date, end_date, booking_id))
    conn.commit()
    conn.close()
    event = {
        'type': 'booking_dates_changed',
        'booking_id': booking_id,
        'start_date': start_date,
        'end_date': end_date
    }
    sendMessageToRabbitMQ(json.dumps(event))
    return jsonify({"message": "Booking dates changed successfully"})

# API to list all bookings
@app.route('/list', methods=['GET'])
def list_bookings():
    conn = sqlite3.connect('booking.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM bookings")
    bookings = cursor.fetchall()
    conn.close()

    return jsonify({"bookings": bookings})


# API to list all available appartments (check for me :) )
@app.route('/listavailableappartments', methods=['GET'])
def list_available_appartments():
    conn = sqlite3.connect('booking.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM availableApartmentList")
    available_appartments = cursor.fetchall()
    conn.close()

    return jsonify({"available_appartments": available_appartments})


#Remove all bookings: 
@app.route('/reset', methods=['DELETE'])
def remove_all_bookings():
    conn = sqlite3.connect('booking.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM bookings")
    conn.commit()
    conn.close()
    return jsonify({"message": "All bookings removed"})

#USEFUL FUNCTIONS
# Check if the apartment exists in the available list
def is_apartment_in_available_list(apartment_id):
    conn = sqlite3.connect('booking.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM availableApartmentList WHERE apartment_id=?", (apartment_id,))
    existing_apartment = cursor.fetchone()
    conn.close()
    if existing_apartment:
        return True
    else:
        return False

# Check if there are existing bookings for the specified dates   
def is_booking_conflict(apartment_id, start_date, end_date):
    conn = sqlite3.connect('booking.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM bookings WHERE apartment_id=? AND ((start_date <= ? AND end_date >= ?) OR (start_date <= ? AND end_date >= ?))",
                   (apartment_id, start_date, start_date, end_date, end_date))
    conflicting_booking = cursor.fetchone()
    conn.close()

    return conflicting_booking is not None

def get_booking_by_id(booking_id):
    conn = sqlite3.connect('booking.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM bookings WHERE id=?", (booking_id,))
    row = cursor.fetchone()
    conn.close()
    # row is a tuple like (id, apartment_id, start_date, end_date, who)
    if not row:
        return None
    return {
        'id': row[0],
        'apartment_id': row[1],
        'start_date': row[2],
        'end_date': row[3],
        'who': row[4]
    }


initialize_apartments()

# Start the RabbitMQ thread
logging.debug('Avvio del thread RabbitMQ')
rabbitmq_thread = threading.Thread(target=run_rabbitmq_consumer)
rabbitmq_thread.start()

if __name__ == '__main__':
    app.run(port=5002)
