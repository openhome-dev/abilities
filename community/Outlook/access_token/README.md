# Microsoft Graph Authentication – Step by Step Guide

## Why We Need This (Simple Explanation)

Microsoft Graph protects user data like email and calendar.

Before your app can access anything, Microsoft must verify:

1. The app is registered  
2. The user signs in  
3. The user gives permission  

After that, Microsoft gives your app an **Access Token**.

The Access Token is required for every request to Microsoft Graph.

Without it, nothing works.

---

## Step 1 – Install Python

Download Python from:

https://www.python.org/downloads/

After installing, open a terminal and type:

python --version

If it shows a version number, Python is installed correctly.

---

## Step 2 – Install Required Library

Install MSAL (Microsoft Authentication Library):


pip install msal

This library handles login and token generation.

---

## Step 3 – Create an Application in Microsoft Entra

1. Go to:  
   https://entra.microsoft.com  

2. Sign in with your Microsoft account.  

3. Click:  
   **Applications**

4. Click:  
   **App registrations**

5. Click:  
   **New registration**

---

## Step 4 – Register the Application

Fill in:

**Name:**  
Anything you want (Example: My Graph App)

**Supported account types:**  
Select:  
Accounts in any organizational directory and personal Microsoft accounts

Leave Redirect URI blank.

Click **Register**.

---

## Step 5 – Copy Your Client ID

After registering, you will see:

**Application (client) ID**

Copy this value.

It looks like a long ID with letters and numbers.

You will paste this into your script.

---

## Step 6 – Enable Public Client Flow

Inside your app registration:

1. Click **Authentication**
2. Scroll down
3. Find:  
   **Allow public client flows**
4. Set it to:  
   **YES**
5. Click **Save**

This is required for device login to work.

---

## Step 7 – Add API Permissions

1. Click **API permissions**
2. Click **Add a permission**
3. Select **Microsoft Graph**
4. Choose **Delegated permissions**
5. Add:
   - `User.Read`
   - `Calendars.ReadWrite`
   - `email`
   - `offline_access`
6. Click **Add permissions**

---

## Step 8 – Update Your Script

Open your `auth.py` file.

Find this line:

CLIENT_ID = "your-client-id"

Replace it with your real Client ID from Entra:

Save the file.

---

## Step 9 – Run the Script

In your terminal:

python auth.py

---

## Step 10 – Complete Device Login

The terminal will display a message like:

Go to https://microsoft.com/devicelogin

Enter the code XXXX-XXXX


Do the following:

1. Open https://microsoft.com/devicelogin in your browser  
2. Enter the code shown in your terminal  
3. Sign in  
4. Click **Accept** when asked for permissions  

---

## Step 11 – Get Your Access Token

After login, your terminal will print:

Access token:
(long text)

That long text is your **Access Token**.

This token is required for every Microsoft Graph API request.
