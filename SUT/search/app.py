import json
import logging
import threading
import time
from flask import Flask, request, jsonify
import sqlite3
import requests

import pika
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)

conn = sqlite3.connect('search.db')
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS apartments
                  (id TEXT PRIMARY KEY, name TEXT, address TEXT, noiselevel INTEGER, floor INTEGER)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS bookings
                  (id TEXT PRIMARY KEY, apartment_id TEXT, start_date TEXT, end_date TEXT, who TEXT)''')
conn.commit()
conn.close()

class RabbitMQListener(threading.Thread):
    def __init__(self, queues):
        threading.Thread.__init__(self)
        self.queues = queues

    def connect_to_rabbitmq(self):
        while True:
            try:
                connection = pika.BlockingConnection(pika.ConnectionParameters('rabbitmq'))
                channel = connection.channel()
                for queue in self.queues:
                    channel.queue_declare(queue=queue)
                logging.debug('Connected to RabbitMQ')
                logging.debug(channel)  # Print the content of the channel
                return connection, channel
            except pika.exceptions.ConnectionClosedByBroker:
                logging.error('Connection to RabbitMQ closed by broker. Retrying...')
            except Exception as e:
                logging.error('Error connecting to RabbitMQ: %s. Retrying...', str(e))

            time.sleep(5)  # Retry the connection every 5 seconds

    def handle_rabbitmq_event(self, ch, method, properties, body):
        logging.debug('Received event from RabbitMQ')
        event = json.loads(body)
        logging.debug('Event: ')
        logging.debug(event)
        # Handle events based on type
        if event['type'] == 'apartment_added':
            self.ap_added(event)
        elif event['type'] == 'apartment_removed':
            self.ap_removed(event['apartment_id'])
        elif event['type'] == 'booking_added':
            self.booking_added(event)
        elif event['type'] == 'booking_canceled':
            self.booking_canceled(event['booking_id'])
        elif event['type'] == 'booking_dates_changed':
            self.booking_dates_changed(event['booking_id'], event['start_date'], event['end_date'])

    def run(self):
        connection, channel = self.connect_to_rabbitmq()
        logging.debug('Starting consuming')
        for queue in self.queues:
            channel.basic_consume(queue=queue, on_message_callback=self.handle_rabbitmq_event, auto_ack=True)
        channel.start_consuming()


    # Handle booking events
    def booking_added(self, event):
        conn = sqlite3.connect('search.db')
        cursor = conn.cursor()
        cursor.execute("INSERT INTO bookings (id, apartment_id, start_date, end_date, who) VALUES (?, ?, ?, ?, ?)",
                       (event['booking_id'], event['apartment_id'], event['start_date'], event['end_date'], event['who']))
        conn.commit()
        conn.close()
        logging.error(f"Booking added for apartment {event['apartment_id']} from {event['start_date']} to {event['end_date']    }")

    def booking_canceled(self, booking_id):
        conn = sqlite3.connect('search.db')
        cursor = conn.cursor()
        cursor.execute("DELETE FROM bookings WHERE id=?", (booking_id,))
        conn.commit()
        conn.close()
        logging.error(f"Booking canceled with ID {booking_id}")

    def booking_dates_changed(self, booking_id, start_date, end_date):
        conn = sqlite3.connect('search.db')
        cursor = conn.cursor()
        cursor.execute("UPDATE bookings SET start_date=?, end_date=? WHERE id=?",
                       (start_date, end_date, booking_id))
        conn.commit()
        conn.close()
        logging.error(f"Booking dates changed for ID {booking_id} to {start_date} - {end_date}")

    # Handle apartment events
    def ap_added(self, event):
        apartment_id = event['apartment_id']

        conn = sqlite3.connect('search.db')
        cursor = conn.cursor()
        cursor.execute("INSERT INTO apartments (id, name, address, noiselevel, floor) VALUES (?, ?, ?, ?, ?)",
                       (apartment_id, event['name'], event['address'], event['noiselevel'], event['floor']))
        conn.commit()
        conn.close()
        logging.debug(f"Apartment {apartment_id} added.")

    def ap_removed(self, apartment_id):
        conn = sqlite3.connect('search.db')
        cursor = conn.cursor()
        cursor.execute("DELETE FROM apartments WHERE id=?", (apartment_id,))
        conn.commit()
        conn.close()

        logging.error(f"Apartment {apartment_id} removed.")



####INIT APPARTMENT ######
def initialize_apartments():
    max_retries = 10  
    retry_delay = 20  
    retry_count = 0

    while retry_count < max_retries:
        try:
            response = requests.get('http://localhost:5000/apartment/list', timeout=5)
            response.raise_for_status()  
            if response.status_code == 200:
                available_apartments = response.json().get('apartments', [])
                
                conn = sqlite3.connect('search.db')
                cursor = conn.cursor()
                for apartment in available_apartments:
                        cursor.execute("SELECT id FROM apartments WHERE id=?", (apartment[0],))
                        existing_apartment = cursor.fetchone()
                        if existing_apartment is None:
                            cursor.execute("INSERT INTO apartments (id, name, address, noiselevel, floor) VALUES (?, ?, ?, ?, ?)",
                                           (apartment[0], apartment[1], apartment[2], apartment[3], apartment[4]))
                conn.commit()
                conn.close()
            else:
                print(f"Error fetching available apartments: {response.status_code}")  
            break  
        except requests.exceptions.RequestException as e:
            retry_count += 1
            logging.error('Error making HTTP request to booking service: %s. Retrying (Attempt %d/%d)...', str(e), retry_count, max_retries)
    
        time.sleep(retry_delay) 
    if retry_count == max_retries:
        logging.error('Failed to make HTTP request after %d attempts.', max_retries)

####INIT BOOKINGS ######
def initialize_bookings():
    max_retries = 10  
    retry_delay = 20  
    retry_count = 0

    while retry_count < max_retries:
        try:
            response = requests.get('http://localhost:5000/booking/list', timeout=5)
            response.raise_for_status()  
            if response.status_code == 200:
                bookings = response.json().get('bookings', [])
        
                conn = sqlite3.connect('search.db')
                cursor = conn.cursor()
                for booking in bookings:
                    cursor.execute("SELECT id FROM bookings WHERE id=?", (booking[0],))
                    existing_booking = cursor.fetchone()
                    if existing_booking is None:
                        cursor.execute("INSERT INTO bookings (id, apartment_id, start_date, end_date, who) VALUES (?, ?, ?, ?, ?)",
                        (booking[0], booking[1], booking[2], booking[3], booking[4]))
                conn.commit()
                conn.close()
            break  
        except requests.exceptions.RequestException as e:
            retry_count += 1
            logging.error('Error making HTTP request to booking service: %s. Retrying (Attempt %d/%d)...', str(e), retry_count, max_retries)
    
        time.sleep(retry_delay) 

    if retry_count == max_retries:
        logging.error('Failed to make HTTP request after %d attempts.', max_retries)

###################################################################
@app.route('/search', methods=['GET'])
def search_apartments():
    start_date = request.args.get('from')
    end_date = request.args.get('to')

    apartments = get_apartments()

    bookings = get_bookings()

    available_apartments = search_available_apartments(apartments, bookings, start_date, end_date)

    return jsonify({"available_apartments": available_apartments})

# API to get the list of apartments
@app.route('/apartmentList', methods=['GET'])
def get_apartment_list():
    apartments = get_apartments()
    return jsonify({"apartments": apartments})

# API to get the list of bookings
@app.route('/bookingList', methods=['GET'])
def get_booking_list():
    bookings = get_bookings()
    return jsonify({"bookings": bookings})

def get_apartments():
    conn = sqlite3.connect('search.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM apartments")
    apartments = cursor.fetchall()
    conn.close()
    return apartments

def get_bookings():
    conn = sqlite3.connect('search.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM bookings")
    bookings = cursor.fetchall()
    conn.close()
    return bookings

def search_available_apartments(apartments, bookings, start_date, end_date):
    available_apartments = []

    for apartment in apartments:
        apartment_id = apartment[0]
        is_available = True

        for booking in bookings:
            if booking[1] == apartment_id:
                booking_start = booking[2]
                booking_end = booking[3]

                if not (end_date < booking_start or start_date > booking_end):
                    is_available = False
                    break

        if is_available:
            available_apartments.append(apartment)

    return available_apartments

initialize_apartments()
initialize_bookings()

# Start the RabbitMQ thread
logging.debug('Starting RabbitMQ listener thread')
rabbitmq_listener_thread = RabbitMQListener(queues=['events', 'bookingEvents'])
rabbitmq_listener_thread.start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
