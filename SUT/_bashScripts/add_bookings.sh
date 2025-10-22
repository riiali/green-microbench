#!/bin/bash

if [ $# -eq 0 ]; then
    echo "Usage: $0 <apartment_id1> [<apartment_id2> ...]"
    exit 1
fi

for apartment_id in "$@"; do
    start_date=$(date -d "+$((RANDOM % 30)) days" +%Y%m%d)
    end_date=$(date -d "$start_date + $((RANDOM % 10 + 1)) days" +%Y%m%d)
    who="Guest$i"

    json_data="{\"apartment_id\":\"$apartment_id\",\"start_date\":\"$start_date\",\"end_date\":\"$end_date\",\"who\":\"$who\"}"

    curl -X POST -H "Content-Type: application/json" -d "$json_data" http://localhost:5000/booking/add

    echo "Booking added for Apartment $apartment_id from $start_date to $end_date by $who"
done
