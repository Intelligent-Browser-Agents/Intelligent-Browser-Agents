import pywhatkit as pwk

# define recipient's phone number (with area code) and message to send them 
phone_number = "+17726073308"
message = "Hello, this is a test from Python!"

# Send the message
pwk.sendwhatmsg(phone_number, message, 18, 12)


