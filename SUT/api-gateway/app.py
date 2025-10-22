from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

# Define the base URLs for the microservices
apartment_microservice_url = 'http://apartment:5000'
booking_microservice_url = 'http://booking:5000'
search_microservice_url = 'http://search:5000'

@app.route('/apartment/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE'])
def forward_to_apartment_microservice(path):
    url = f'{apartment_microservice_url}/{path}'
    response = requests.request(method=request.method, url=url, json=request.get_json(), params=request.args)
    return jsonify(response.json()), response.status_code

@app.route('/booking/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE'])
def forward_to_booking_microservice(path):
    url = f'{booking_microservice_url}/{path}'
    response = requests.request(method=request.method, url=url, json=request.get_json(), params=request.args)
    return jsonify(response.json()), response.status_code

@app.route('/search/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE'])
def forward_to_search_microservice(path):
    url = f'{search_microservice_url}/{path}'
    response = requests.request(method=request.method, url=url, json=request.get_json(), params=request.args)
    return jsonify(response.json()), response.status_code

if __name__ == '__main__':
    app.run(port=5000)