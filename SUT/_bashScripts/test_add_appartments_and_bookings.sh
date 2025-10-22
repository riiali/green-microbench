#!/bin/bash

# Number of apartments to create
N=100
API_BASE_URL="http://localhost:5000"

start_time=$(date +%s)

echo "Adding $N apartments..."

# Step 1: Add Apartments
apartment_ids=()
for i in $(seq 1 $N); do
    name="Apartment$i"
    address="City$i"
    noiselevel=$((RANDOM % 10 + 1))
    floor=$((RANDOM % 10))

    json_data="{\"name\":\"$name\",\"address\":\"$address\",\"noiselevel\":$noiselevel,\"floor\":$floor}"

    response=$(curl -s -X POST -H "Content-Type: application/json" -d "$json_data" "$API_BASE_URL/apartment/add")
    
    apartment_id=$(echo "$response" | grep -oP '(?<="id":")[^"]*')
    
    if [ -n "$apartment_id" ]; then
        apartment_ids+=("$apartment_id")
        echo "Apartment $i added with ID $apartment_id"
    else
        echo "Failed to add Apartment $i"
    fi
done

# Step 2: Add Bookings
echo "Creating bookings for added apartments..."

for apartment_id in "${apartment_ids[@]}"; do
    echo "Creating bookings for Apartment $apartment_id..."
    start_date=$(date -d "+$((RANDOM % 30)) days" +%Y-%m-%d)
    end_date=$(date -d "$start_date + $((RANDOM % 10 + 1)) days" +%Y-%m-%d)
    who="Guest$((RANDOM % 1000))"

    json_data="{\"apartment_id\":\"$apartment_id\",\"start_date\":\"$start_date\",\"end_date\":\"$end_date\",\"who\":\"$who\"}"

    response=$(curl -s -X POST -H "Content-Type: application/json" -d "$json_data" "$API_BASE_URL/booking/add")

    if echo "$response" | grep -q "Booking added"; then
        echo "Booking added for Apartment $apartment_id from $start_date to $end_date by $who"
    else
        echo "Failed to create booking for Apartment $apartment_id"
    fi
done

end_time=$(date +%s)
elapsed_time=$((end_time - start_time))

echo "Process completed in $elapsed_time seconds."
