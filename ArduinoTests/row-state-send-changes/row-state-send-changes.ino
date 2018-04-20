// Arduino Control for Row A
// Josh & Dom

#include <Wire.h>

char ROW = 'A';
int RPiInput = 0;
int changeState = -1;
#define SLAVE_ADDRESS 0x04

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
    // output received, print data
    Serial.println("Data received: " + String(RPiInput));
  }

  // check for changes
  int oldStates[8];
  for (int i = 0; i < 8; i++) {
    oldStates[i] = states[i];
  }
  // update states
  setStates();
  // set change state to default, no changes
  changeState = -1;
  for (int i = 0; i < 8; i++) {
    if (oldStates[i] != states[i]) {
      if (changeState != -1) {
        // there has been a change, erase other changes (can only send one at a time)
        states[i] = oldStates[i];
      } else {
        changeState = i; // 0-7 scale
      }
    }
  }

  // states updated, if any changes only one reflected. 
  // send back changeState
  
  // RPiInput stores desired column, update data and send

}

void sendData() {
  // send back row that changed (or -1 if no changes)
  Wire.write(changeState);
  //int index = RPiInput - 1;
  //Wire.write(states[index]);
}

// Arduino side only:
void loop() {
  // set states of reed switches
  //setStates();
  //getStates();
  delay(1);
  detectChange();
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
}


