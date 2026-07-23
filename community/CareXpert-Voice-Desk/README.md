# 🏥 CareXpert Voice Desk

**An intelligent, voice-first hospital management and triage system.**
*Built for the OpenHome AI Hackathon – Islamabad, July 2026*

## 📖 Overview

CareXpert Voice Desk modernizes the traditional hospital waiting room by replacing manual data entry with a real-time, conversational AI agent. Powered by the OpenHome SDK, it seamlessly handles patient registration, emergency triage, queue prioritization, and doctor prescriptions entirely through voice commands.

The backend logic connects directly to a live Supabase PostgreSQL database, ensuring that front-end React dashboards update instantly as the AI processes requests.

## ✨ Key Features

* **🗣️ Conversational Receptionist:** Extracts Name, Age, and Gender from natural speech using intelligent LLM parsing.
* **🚨 Smart Triage & Priority Queueing:** Automatically categorizes patients into OPD or Emergency. Emergency patients are further triaged into "Critical" or "Normal," ensuring the doctor calls the most urgent cases first.
* **🩺 Doctor Dashboard:** A secure sub-menu for doctors to assign medicines, update existing prescriptions, and set follow-up dates via voice.
* **📊 Voice-Driven Analytics:** The system tracks `created_at` and `completed_at` timestamps to instantly calculate and report the daily **Average Wait Time** on command.
* **📅 Patient History & Follow-ups:** Capable of retrieving past visit records and listing patients scheduled for follow-ups on the current day.
* **⏩ Queue Management:** Handles "No-Shows" by allowing the doctor to skip tokens, keeping the queue moving smoothly.

## 🛠️ Tech Stack

* **Voice AI Framework:** OpenHome SDK (Python)
* **Database:** Supabase (PostgreSQL REST API)
* **Frontend integration (Paired):** React.js
* **Data Parsing:** Regex & JSON Extraction natively handled in Python.

## 🚀 Setup & Installation

1. **Clone the repository:**
```bash
git clone https://github.com/yourusername/carexpert-voice-desk.git
cd carexpert-voice-desk

```


2. **Install dependencies:**
Ensure `requests` is installed for Supabase REST API communication.
```bash
pip install -r requirements.txt

```


3. **Database Configuration:**
The system requires a Supabase table named `patients` with the following schema:
* `id` (BIGINT, Primary Key)
* `token_number` (TEXT)
* `patient_name` (TEXT)
* `age` (INTEGER)
* `gender` (TEXT)
* `visit_type` (TEXT)
* `severity` (TEXT)
* `prescription` (TEXT)
* `status` (TEXT)
* `follow_up_date` (TEXT)
* `date` (TEXT)
* `created_at` & `completed_at` (TIMESTAMPTZ)


4. **Deploy to OpenHome:**
* Create a new Ability on the OpenHome Dashboard.
* Paste the `main.py` code into the DevKit.
* Set the trigger phrases (e.g., "Open CareXpert", "Start hospital reception").



## 🎙️ Voice Commands Guide (Testing)

**Main Menu:**

* *"Add a patient"* (Routes to Reception)
* *"Doctor dashboard"* (Routes to Doctor Menu)

**Reception:**

* *"Ali is a 30-year-old male."*
* *"Emergency"* -> *"Critical"*

**Doctor Dashboard:**

* *"Call the next patient"*
* *"Assign a prescription"* -> *"Token E1"* -> *"Panadol"* -> *"Follow up in 3 days"*
* *"Check the queue"*
* *"Patient history"*
* *"Average wait time"*
* *"Go back"* (Returns to Main Menu)
