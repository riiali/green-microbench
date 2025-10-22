#!/bin/bash

if [ $# -eq 0 ]; then
    echo "Usage: $0 <apartment_id>"
    exit 1
fi

apartment_id="$1"

api_url="http://localhost:5000/apartment/remove?id=$apartment_id"

response=$(curl -X DELETE -s "$api_url")


if [ "$response" == '{"message":"apartment canceled successfully"}' ]; then
    echo "apartment with ID $apartment_id canceled successfully"
else
    echo "Error canceling apartment with ID $apartment_id"
fi
