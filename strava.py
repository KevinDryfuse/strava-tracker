import requests
import time
import json
import os
import csv
from dotenv import load_dotenv
from flask import Flask, jsonify

load_dotenv()

# Load credentials from .env file
CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
REDIRECT_URI = os.getenv('REDIRECT_URI')
REFRESH_TOKEN_FILE = 'refresh_token.txt'
BASE_URL = 'https://www.strava.com/api/v3'

# Constants
GOAL_MILES = 1500
RUN_INTERVAL = 15 * 60  # Interval in seconds (15 minutes)
ACCESS_TOKEN = None  # Global variable to store the current access token

# Flask app setup
app = Flask(__name__)


def date_to_unix_timestamp(date_str):
    """Convert a date string to a Unix timestamp."""
    return int(time.mktime(time.strptime(date_str, '%Y-%m-%d')))


def load_refresh_token():
    """Load the refresh token from a file."""
    try:
        with open(REFRESH_TOKEN_FILE, 'r') as file:
            return file.read().strip()
    except FileNotFoundError:
        print(f'{REFRESH_TOKEN_FILE} not found. Please initialize the refresh token.')
        return None


def save_refresh_token(token):
    """Save the refresh token to a file."""
    with open(REFRESH_TOKEN_FILE, 'w') as file:
        file.write(token)


def reauthorize_app():
    """Reauthorize the app and retrieve new access and refresh tokens."""
    print('Reauthorizing the app to get a new access token...')
    authorization_url = (
        f'https://www.strava.com/oauth/authorize'
        f'?client_id={CLIENT_ID}'
        f'&response_type=code'
        f'&redirect_uri={REDIRECT_URI}'
        f'&approval_prompt=force'
        f'&scope=read,activity:read,activity:read_all'
    )
    print('Visit the following URL to authorize the app:')
    print('Authorization URL:', authorization_url)
    auth_code = input('Enter the authorization code from the URL after approval: ')

    # Exchange authorization code for tokens
    token_url = f'{BASE_URL}/oauth/token'
    payload = {
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'code': auth_code,
        'grant_type': 'authorization_code',
    }
    response = requests.post(token_url, data=payload)
    response.raise_for_status()
    tokens = response.json()

    print('New access token and refresh token retrieved:')
    global ACCESS_TOKEN
    ACCESS_TOKEN = tokens['access_token']
    save_refresh_token(tokens['refresh_token'])
    return ACCESS_TOKEN


def refresh_access_token():
    """Refresh the access token using the refresh token."""
    global ACCESS_TOKEN
    refresh_token = load_refresh_token()
    if not refresh_token:
        return reauthorize_app()

    url = f'{BASE_URL}/oauth/token'
    payload = {
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token,
    }
    response = requests.post(url, data=payload)
    if response.status_code != 200:
        print('Failed to refresh token. Initiating reauthorization...')
        return reauthorize_app()

    tokens = response.json()
    ACCESS_TOKEN = tokens['access_token']
    save_refresh_token(tokens['refresh_token'])
    return ACCESS_TOKEN


def fetch_activities(after_timestamp):
    """Fetch hiking activities from the Strava API."""
    global ACCESS_TOKEN
    url = f'{BASE_URL}/athlete/activities'
    headers = {'Authorization': f'Bearer {ACCESS_TOKEN}'}
    activities = []
    page = 1
    max_pages = 50  # Safety limit to avoid infinite loops

    while page <= max_pages:
        params = {'after': after_timestamp, 'per_page': 200, 'page': page}
        response = requests.get(url, headers=headers, params=params)

        # Handle rate limits
        if response.status_code == 429:
            reset_time = int(response.headers.get('X-RateLimit-Reset', 0))
            wait_time = max(reset_time - int(time.time()), 0)
            print(f'Rate limit reached. Waiting for {wait_time} seconds...')
            time.sleep(wait_time or 15 * 60)  # Wait for rate limit reset
            continue

        if response.status_code == 401:
            print('Access token is invalid or expired. Refreshing...')
            ACCESS_TOKEN = refresh_access_token()
            headers = {'Authorization': f'Bearer {ACCESS_TOKEN}'}
            continue

        response.raise_for_status()
        data = response.json()

        if not data:
            break

        # Filter for hiking activities
        hiking_activities = [
            {
                'id': activity['id'],
                'date': activity['start_date'],
                'type': activity['type'],
                'distance': activity['distance'] / 1609.34,  # Convert meters to miles
                'suffer_score': activity.get('suffer_score', None),
                'average_heartrate': activity.get('average_heartrate', None)
            }
            for activity in data if activity['type'] == 'Hike'
        ]
        activities.extend(hiking_activities)
        print(f'Page {page}: Retrieved {len(hiking_activities)} hiking activities.')
        page += 1

    print(f'Finished fetching {len(activities)} hiking activities.')
    return activities


def write_activities_to_csv(activities, filename='hiking_activities.csv'):
    """Write activities to a CSV file."""
    with open(filename, mode='w', newline='') as file:
        writer = csv.DictWriter(file,
                                fieldnames=['id', 'date', 'type', 'distance', 'suffer_score', 'average_heartrate'])
        writer.writeheader()
        writer.writerows(activities)
    print(f'Activities saved to {filename}.')


@app.route('/activities', methods=['GET'])
def get_activities():
    """REST endpoint to retrieve activities from the CSV file."""
    try:
        with open('hiking_activities.csv', mode='r') as file:
            reader = csv.DictReader(file)
            activities = [row for row in reader]
        return jsonify(activities), 200
    except FileNotFoundError:
        return jsonify({'error': 'Activities file not found.'}), 404


# Endpoint to return raw JSON data
@app.route('/raw-activities', methods=['GET'])
def get_raw_activities():
    '''REST endpoint to retrieve raw activities data from the JSON file.'''
    try:
        with open('hiking_activities.json', 'r') as file:
            activities = json.load(file)
        return jsonify(activities), 200
    except FileNotFoundError:
        return jsonify({'error': 'Raw activities file not found.'}), 404


def main():
    """Main function to handle Strava API data retrieval and storage."""
    global ACCESS_TOKEN
    try:
        print('Refreshing access token...')
        ACCESS_TOKEN = refresh_access_token()
        print('Access token refreshed successfully.')

        # Define the date since you want to fetch activities
        since_date = '2025-01-01'
        after_timestamp = date_to_unix_timestamp(since_date)

        # Fetch activities
        print(f'Fetching activities since {since_date}...')
        activities = fetch_activities(after_timestamp)

        # Save activities to JSON and CSV
        with open('hiking_activities.json', 'w') as file:
            json.dump(activities, file, indent=4)
        print('Activities saved to hiking_activities.json.')

        write_activities_to_csv(activities)

        # Logging
        total_mileage = sum(activity['distance'] for activity in activities)
        remaining_miles = GOAL_MILES - total_mileage
        most_recent_hike = max(activities, key=lambda x: x['date'], default=None)
        most_recent_distance = most_recent_hike['distance'] if most_recent_hike else 0
        print(f'The last hike was {most_recent_distance:.2f} miles! The total distance covered this year is {total_mileage:.2f} and there are {remaining_miles:.2f} miles remaining!')

    except requests.exceptions.RequestException as e:
        print(f'Error: {e}')


if __name__ == '__main__':
    # Start Flask in a background thread
    import threading

    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5000, debug=False), daemon=True).start()

    # Run the main workflow in a loop
    while True:
        main()
        print(f'Sleeping for {RUN_INTERVAL // 60} minutes before the next run...')
        time.sleep(RUN_INTERVAL)
