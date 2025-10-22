#!/bin/bash

if [ $# -eq 0 ]; then
    echo "Usage: $0 <booking_id>"
    exit 1
fi

booking_id="$1"

api_url="http://localhost:5000/booking/cancel?id=$booking_id"

response=$(curl -X DELETE -s "$api_url")


if [ "$response" == '{"message":"Booking canceled successfully"}' ]; then
    echo "Booking with ID $booking_id canceled successfully"
else
    echo "Error canceling booking with ID $booking_id"
fi
