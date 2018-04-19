
#include <Wire.h>

#define SLAVE_ADDRESS 0x04
int number = 0;
int state = 0;

const int REED_PIN = 2;
const int LED_PIN = 5;

void setup() {
  pinMode(13, OUTPUT);
  Serial.begin(9600); // start serial for output
  // initialize i2c as slave
  Wire.begin(SLAVE_ADDRESS);

  // define callbacks for i2c communication
  Wire.onReceive(receiveData);
  Wire.onRequest(sendData);
  Serial.println("i2c ready.");

  pinMode(REED_PIN, INPUT_PULLUP);
  Serial.println("Reed Switch ready.");
}

void loop() {
  delay(100);
}

// callback for received data
void receiveData(int byteCount){

  while(Wire.available()) {
  number = Wire.read();
  Serial.print("data received: ");
  Serial.println(number);

  // check reed switch status
   int proximity = digitalRead(REED_PIN);

  number = proximity;
   
   if (proximity == LOW) {
      //Serial.println("Switch activated");
      //digitalWrite(LED_PIN, HIGH); // turn on light
   } else {
      digitalWrite(LED_PIN, LOW);
   }
  
  if (number == 1){

  if (state == 0){
    digitalWrite(13, HIGH); // set the LED on
    state = 1;
  }
  else{
    digitalWrite(13, LOW); // set the LED off
    state = 0;
  }
}
}
}

// callback for sending data
void sendData(){
  // send back data about reed switch for this reed switch
  // number stores proximity value of reed switch
  Wire.write(number);
  Wire.write(number);
}

