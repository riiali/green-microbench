import json
import logging
import time
from venv import logger
from flask import Flask, request, jsonify
import sqlite3
import uuid
import pika
import pika

app = Flask(__name__)

# Initialize SQLite database
conn = sqlite3.connect('apartment.db')
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS apartments
                  (id TEXT PRIMARY KEY, name TEXT, address TEXT, noiselevel INTEGER, floor INTEGER)''')
conn.commit()
conn.close()

def connectToRabbitMQ(message):
    try:
        connection = pika.BlockingConnection(pika.ConnectionParameters('rabbitmq'))
        logging.debug('ConnecToRabbit')
        try:
            channel = connection.channel()
            channel.queue_declare(queue='events')
            channel.basic_publish(exchange='', routing_key='events', body=message)
        except Exception as e:
            logger.error("Error in RabbitMQ channel setup: %s", str(e))
        finally:
            connection.close()
    except Exception as e:
        logger.error("Error connecting to RabbitMQ: %s", str(e))


# API to add an apartment
@app.route('/add', methods=['POST'])
def add_apartment():
    data = request.get_json()
    apartment_id = str(uuid.uuid4())
    name = data['name']
    address = data['address']
    noiselevel = data['noiselevel']
    floor = data['floor']

    conn = sqlite3.connect('apartment.db')
    cursor = conn.cursor()
    cursor.execute("INSERT INTO apartments VALUES (?, ?, ?, ?, ?)",
                   (apartment_id, name, address, noiselevel, floor))
    conn.commit()
    conn.close()
    apartment_data = {
        'type': 'apartment_added',
        'apartment_id': apartment_id,
        'name': name,
        'address': address,
        'noiselevel': noiselevel,
        'floor': floor
    }
    logger.debug("Apartment added")
    connectToRabbitMQ(json.dumps(apartment_data))
    return jsonify({"message": "Apartment added successfully", "id": apartment_id})

# API to remove an apartment
@app.route('/remove', methods=['DELETE'])
def remove_apartment():
    apartment_id = request.args.get('id')

    conn = sqlite3.connect('apartment.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM apartments WHERE id=?", (apartment_id,))
    conn.commit()
    conn.close()
    connectToRabbitMQ(json.dumps({'type': 'apartment_removed'}))
    return jsonify({"message": "Apartment removed successfully"})

#Remove all apartments
@app.route('/reset', methods=['DELETE'])
def remove_all_apartments():
    conn = sqlite3.connect('apartment.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM apartments")
    conn.commit()
    conn.close()
    connectToRabbitMQ(json.dumps({'type': 'apartment_removed_all'}))
    return jsonify({"message": "All apartments removed successfully"})

# API to list all apartments
@app.route('/list', methods=['GET'])
def list_apartments():
    conn = sqlite3.connect('apartment.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM apartments")
    apartments = cursor.fetchall()
    conn.close()

    return jsonify({"apartments": apartments})

if __name__ == '__main__':
    app.run(port=5001)
