#!/bin/bash

get_apartment_count() {
    echo "$1" | grep -o '],\[' | wc -l
}

response1=$(curl -s http://localhost:5001/list)
response2=$(curl -s http://localhost:5002/listavailableappartments)
response3=$(curl -s http://localhost:5003/apartmentList)

count1=$(get_apartment_count "$response1")
count2=$(get_apartment_count "$response2")
count3=$(get_apartment_count "$response3")

echo "Numero di appartamenti APARTMENTS: $count1"
echo "Numero di appartamenti BOOKINGS: $count2"
echo "Numero di appartamenti SEARCH: $count3"
