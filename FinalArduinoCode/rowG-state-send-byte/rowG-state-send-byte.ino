
// Arduino Control for Row G
// Josh & Dom

#include <Wire.h>
#include <math.h>

char ROW = 'G';
int RPiInput = 0;
int changeState = -1;
int bitValue = 0;

#define SLAVE_ADDRESS 0x0a

// define Reed switch ports
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
  Wire.onReceive(receiveData);
  Wire.onRequest(sendData);
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

void receiveData(int byteCount) {
  while(Wire.available()) {
    RPiInput = Wire.read();
  }

  // set states and update bitValue
  setStates();
}

void sendData() {
  Serial.println(bitValue);
  // send back bitValue
  Wire.write(bitValue);
}

// Arduino side
  // states updated, if any changes only one reflected. 
  // send back changeState only:
void loop() {
  // set states of reed switches
  //setStates();
  //getStates();
  delay(1);
  //detectChange();
}

void getStates() {
  for (int i = 0; i < 8; i++) {
    if (states[i] == LOW) {
      Serial.println("Switch " + String(i + 1) + " activated");
    }
  }
}

void detectChange() {
  int oldStates[8];
  for (int i = 0; i < 8; i++) {
    oldStates[i] = states[i];
  }
  // update states
  setStates();
  // detect change
  for (int i = 0; i < 8; i++) {
    if (oldStates[i] != states[i]) {
      if (states[i] == LOW) {
        Serial.println("Switch " + String(i + 1) + " activated.");
      } else {
        Serial.println("Switch " + String(i + 1) + " deactivated.");
      }
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

  bitValue = 0;
  for (int i = 0; i < 8; i++) {
    //Serial.println(states[i]);
    bitValue = bitValue + round(states[i]*pow(2, i));
  }
}


