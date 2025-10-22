#!/bin/bash

if [ "$#" -ne 3 ]; then
    echo "Usage: $0 <booking_id> <new_start_date> <new_end_date>"
    exit 1
fi

booking_id="$1"
new_start_date="$2"
new_end_date="$3"

api_url="http://localhost:5000/booking/change"

response=$(curl -X PUT -H "Content-Type: application/json" -d "{\"id\":\"$booking_id\",\"start_date\":\"$new_start_date\",\"end_date\":\"$new_end_date\"}" -s "$api_url")

if [ "$response" == '{"message":"Booking dates changed successfully"}' ]; then
    echo "Booking with ID $booking_id dates changed successfully"
else
    echo "Error changing dates for booking with ID $booking_id"
fi
