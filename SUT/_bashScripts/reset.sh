#reset all 
echo "resetting all"
curl -X DELETE http://localhost:5000/booking/reset
curl -X DELETE http://localhost:5000/apartment/reset