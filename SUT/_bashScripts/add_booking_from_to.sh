#!/bin/bash

if [ $# -ne 4 ]; then
    echo "Usage: $0 <apartment_id> <start_date> <end_date> <who>"
    exit 1
fi

apartment_id=$1
start_date=$2
end_date=$3
who=$4

json_data="{\"apartment_id\":\"$apartment_id\",\"start_date\":\"$start_date\",\"end_date\":\"$end_date\",\"who\":\"$who\"}"

curl -X POST -H "Content-Type: application/json" -d "$json_data" http://localhost:5000/booking/add

echo "Booking added for Apartment $apartment_id from $start_date to $end_date by $who"
