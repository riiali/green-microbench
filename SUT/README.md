# Microservices

This project implements a microservices architecture with three services: Apartment, Booking, and Search. Additionally, an API Gateway is used to route requests to the appropriate microservice.

## Project Structure

- **apartment-service**: Microservice for managing apartment data.
- **booking-service**: Microservice for managing booking data.
- **search-service**: Microservice for searching available apartments based on bookings.
- **api-gateway**: API Gateway for routing requests to the respective microservices.

## Usage
### apartment-service:
**http://localhost:5000/apartment/list** lists all apartments
#### Scripts
##### add_appartment.sh
**Usage**
bash ./add:appartment.sh
**Result**
adds 10 apartment with random noiselevel and flor (between 1 and 10)
##### delete_appartment.sh
**Usage**
bash ./add:appartment.sh <apartment_id>
**Result**
deletes apartment with <apartment_id>

### booking-service:
**http://localhost:5000/booking/list** lists all bookings
**http://localhost:5000/booking//listavailableappartments** lists all apartments from booking (just for checking)

#### Scripts
##### add_bookings.sh
**Usage**
bash ./add_bookings.sh <apartment_id> [<apartment_id2> <apartment_id3> ... ]
**Result**
adds as many random bookings as apartment id provided. 

