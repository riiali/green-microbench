#!/bin/bash

for i in {1..10}
do
    name="Apartment$i"
    address="City$i"
    noiselevel=$((RANDOM % 10 + 1))
    floor=$((RANDOM % 10))

    json_data="{\"name\":\"$name\",\"address\":\"$address\",\"noiselevel\":$noiselevel,\"floor\":$floor}"

    curl -X POST -H "Content-Type: application/json" -d "$json_data" http://localhost:5000/apartment/add

    echo "Apartment $i added"
done
