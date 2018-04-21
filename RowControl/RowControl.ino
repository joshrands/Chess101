// Arduino Control for Row A
// Josh & Dom

#include <Wire.h>

char ROW = 'A';
int number = 0;
#define SLAVE_ADDRESS 0x04

// define Reed switch ports
int COLS[8] = {2, 3, 4, 5, 6, 7, 8, 9};
const int COL1 = 2;
const int COL2 = 3;
const int COL3 = 4;
const int COL4 = 5;
const int COL5 = 6;
const int COL6 = 7;
const int COL7 = 8;
const int COL8 = 9;

int states[8];

//const int LED_PIN = 5;

void setup() {
  //pinMode(13, OUTPUT);
  
  Serial.begin(9600); // start serial for output
  // initialize i2c as slave
  Wire.begin(SLAVE_ADDRESS);

  // define callbacks for i2c communication
  Wire.onReceive(receiveData);
  Wire.onRequest(sendData);
  Serial.println("i2c Row " + String(ROW) + " ready.");

  // define reed switch ports
  pinMode(COLS[0], INPUT_PULLUP);
  pinMode(COLS[1], INPUT_PULLUP);
  pinMode(COLS[2], INPUT_PULLUP);
  pinMode(COLS[3], INPUT_PULLUP);
  pinMode(COLS[4], INPUT_PULLUP);
  pinMode(COLS[5], INPUT_PULLUP);
  pinMode(COLS[6], INPUT_PULLUP);
  pinMode(COLS[7], INPUT_PULLUP);
  Serial.println("All sensors ready.");
}

void loop() {
  delay(100);
}

// callback for received data
// Pi asking arduino for data, read state of reed switches
void receiveData(int byteCount){

  while(Wire.available()) {
  number = Wire.read();
  Serial.print("data received: "); // TODO: Delete this
  Serial.println(number);

  // check reed switch status
  //int proximity = digitalRead(REED_PIN);

  for (int i = 0; i < 8; i++) {
    states[i] = digitalRead(COLS[i]);
    if (states[i] == LOW) {
      Serial.println("Switch activated");
    }
  }
  /*
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
  */
}
}


// callback for sending data
void sendData(){
  Serial.println("Sending data...");
  for (int i = 0; i < 8; i++) {
    states[i] = digitalRead(COLS[i]);
    if (states[i] == LOW) {
      Serial.println("Switch activated");
    }
  }
//  Wire.write(states, 8);
  // send back data about reed switch for this reed switch
  // number stores proximity value of reed switch
  /*
  for (int i = 0; i < 8; i++) {
    if (states[i] == LOW) {
      Wire.write();
    } else {
      Wire.write(0);
    }
  }
  */
}

