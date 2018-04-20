// Arduino Control for Row A
// Josh & Dom

#include <Wire.h>

char ROW = 'A';
int RPiInput = 0;
#define SLAVE_ADDRESS 0x04

// define Reed switch ports
const int REED_PORTS[8] = {2, 3, 4, 5, 6, 7, 8, 9};
const int COL1 = 2;
const int COL2 = 3;
const int COL3 = 4;
const int COL4 = 5;
const int COL5 = 6;
const int COL6 = 7;
const int COL7 = 8;
const int COL8 = 9;

int states[8] = {1, 1, 1, 1, 1, 1, 1, 1}; // initialize states to closed

void setup() {
  
  Serial.begin(9600); // start serial for output
  // initialize i2c as slave
  Wire.begin(SLAVE_ADDRESS);

  // define callbacks for i2c communication
  //Wire.onReceive(receiveData);
  //Wire.onRequest(sendData);
  Serial.println("i2c Row " + String(ROW) + " ready.");

  // define reed switch ports
  pinMode(COL1, INPUT_PULLUP);
  pinMode(COL2, INPUT_PULLUP);
  pinMode(COL3, INPUT_PULLUP);
  pinMode(COL4, INPUT_PULLUP);
  pinMode(COL5, INPUT_PULLUP);
  pinMode(COL6, INPUT_PULLUP);
  pinMode(COL7, INPUT_PULLUP);
  pinMode(COL8, INPUT_PULLUP);
  Serial.println("All sensors ready.");
}

void loop() {
  /*
  for (int i = 0; i < 8; i++) {
    states[i] = digitalRead(REED_PORTS[i]);
    if (states[i] == LOW) {
      Serial.println("Switch " + String(i) + " activated");
    }
  }
  */
  /*
  int proximity = digitalRead(COL1);
  if (proximity == LOW) {
    Serial.println("Switch activated");
  }
  */
  setStates();
  getStates();
  
}

void getStates() {
  for (int i = 0; i < 8; i++) {
    if (states[i] == LOW) {
      Serial.println("Switch " + String(i + 1) + " activated");
    }
  }
}

void setStates() {
  states[0] = digitalRead(COL1);
  states[1] = digitalRead(COL2);
  states[2] = digitalRead(COL3);
  states[3] = digitalRead(COL4);
  states[4] = digitalRead(COL5);
  states[5] = digitalRead(COL6);
  states[6] = digitalRead(COL7);
  states[7] = digitalRead(COL8);
}


