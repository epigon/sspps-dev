from app.cred import CANVAS_API_BASE, CANVAS_API_TOKEN, PANOPTO_API_BASE, PANOPTO_CLIENT_ID, PANOPTO_CLIENT_SECRET
from app.models import db, ScheduledRecording, CalendarGroup, CalendarGroupSelection
from app.utils import permission_required
from bs4 import BeautifulSoup
from .canvas import get_canvas_courses, get_canvas_events, chunked_list
from datetime import datetime, timezone, timedelta
from flask import render_template, request, Blueprint, jsonify
from flask_login import login_required
from icalendar import Calendar, Event, vText
from os.path import dirname, join, abspath
from .panopto_oauth2 import PanoptoOAuth2
import argparse
import os
import pytz
import re
import requests
import sys
import urllib3

sys.path.insert(0, abspath(join(dirname(__file__), '..', 'common')))

bp = Blueprint('scheduler', __name__, url_prefix='/scheduler')

PACIFIC_TZ = pytz.timezone("America/Los_Angeles")
PANOPTO_PARENT_FOLDER = '66a0fa02-94a9-4fb9-ae75-aa71011bd7fc'

CALENDAR_FOLDER = os.path.join("app","static","calendars")
os.makedirs(CALENDAR_FOLDER, exist_ok=True)

mainAccountID = 1	
HSAccountID = 9	
SOMAccountID = 445	
SSPPSAccountID = 50 

# Routes to Webpages
@bp.before_request
@login_required
def before_request():
    pass

def panopto_login():
    args = argparse.Namespace(
        server=PANOPTO_API_BASE,
        client_id=PANOPTO_CLIENT_ID,
        client_secret=PANOPTO_CLIENT_SECRET,
        skip_verify=True
    )
  
    if args.skip_verify:
        # This line is needed to suppress annoying warning message.
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # Use requests module's Session object in this example.
    # ref. https://2.python-requests.org/en/master/user/advanced/#session-objects
    requests_session = requests.Session()
    requests_session.verify = not args.skip_verify

    # Load OAuth2 logic
    oauth2 = PanoptoOAuth2(args.server, args.client_id, args.client_secret, not args.skip_verify)

    # Initial authorization
    authorization(requests_session, oauth2)
    return requests_session, oauth2, args

def authorization(requests_session, oauth2):
    # Go through authorization
    access_token = oauth2.get_access_token_authorization_code_grant()
    # Set the token as the header of requests
    requests_session.headers.update({'Authorization': 'Bearer ' + access_token})

def inspect_response_is_unauthorized(response):
    '''
    Inspect the response of a requets' call, and return True if the response was Unauthorized.
    An exception is thrown at other error responses.
    Reference: https://stackoverflow.com/a/24519419
    '''
    if response.status_code // 100 == 2:
        # Success on 2xx response.
        return False

    if response.status_code == requests.codes.unauthorized:
        # print('Unauthorized. Access token is invalid.')
        return True

    # Throw unhandled cases.
    response.raise_for_status()

def get_panopto_folders():

    requests_session, oauth2, args = panopto_login()
    folders = []
    # Call Panopto API (getting sub-folders from top level folder) repeatedly
    page_number = 0
    page_size = 50  # You can adjust this up to Panopto's max limit

    while True:
        # print(f'Calling GET /api/v1/folders/{PANOPTO_PARENT_FOLDER}/children?pageNumber={page_number}')
        url = f'https://{args.server}/Panopto/api/v1/folders/{PANOPTO_PARENT_FOLDER}/children'
        params = {
            'pageNumber': page_number,
            'maxNumberResults': page_size
        }
        resp = requests_session.get(url=url, params=params)

        if inspect_response_is_unauthorized(resp):
            authorization(requests_session, oauth2)
            resp = requests_session.get(url=url, params=params)

        data = resp.json()
        results = data.get("Results", [])
        for folder in results:
            # if any("spps" in str(value).lower() for value in folder.values()):
            folders.append({"id": folder['Id'], "name": folder['Name']})

        if len(results) < page_size:
            break  # We've reached the last page

        page_number += 1
    # print(folders)
    return folders

def get_panopto_recorders():
    requests_session, oauth2, args = panopto_login()

    recorders = []
    page_number = 0
    page_size = 50  # You can adjust this up to Panopto's max limit

    while True:
        # print('Calling GET /api/v1/remoteRecorders endpoint')
        url = 'https://{0}/Panopto/api/remoteRecorders'.format(args.server)
        params = {
            'pageNumber': page_number,
            'maxNumberResults': page_size
        }
        resp = requests_session.get(url=url, params=params)

        if inspect_response_is_unauthorized(resp):
            authorization(requests_session, oauth2)
            resp = requests_session.get(url=url, params=params)

        data = resp.json()
        # results = data.get("Results", [])
        for recorder in data:
            recorders.append({"id": recorder['Id'], "name": recorder['Name']})

        if len(data) < page_size:
            break  # We've reached the last page

        page_number += 1
    # print(folders)
    return recorders

# def get_canvas_courses(account="SSPPS", blueprint=False):
#     """
#     Fetches all Canvas courses for the authenticated user using pagination.

#     Args:
#         base_url (str): Base URL of the Canvas instance (e.g., 'https://canvas.instructure.com')
#         access_token (str): Bearer token for authentication.
#         per_page (int): Number of courses per page.

#     Returns:
#         list: List of all course dictionaries.
#     """
#     if account == "HS":
#         accountID = HSAccountID
#     elif account == "SSPPS":
#         accountID = SSPPSAccountID
#     elif account == "SOM":
#         accountID = SOMAccountID
#     else:
#         accountID = mainAccountID
    
#     headers = {'Authorization': f'Bearer {CANVAS_API_TOKEN}'}
#     params = {'per_page': 100, 
#               "blueprint": blueprint, 
#               "include[]": ["term","account_name"]}
#     url = f"{CANVAS_API_BASE}/accounts/{accountID}/courses"
#     all_courses = []

#     while url:
#         # print(url)
#         response = requests.get(url, headers=headers, params=params)
#         response.raise_for_status()
#         all_courses.extend(response.json())

#         # Parse the Link header for next page
#         links = response.headers.get("Link", "")
#         next_url = None
#         for link in links.split(","):
#             if 'rel="next"' in link:
#                 next_url = link[link.find("<") + 1:link.find(">")]
#                 break
#         url = next_url
#         params = None  # After the first request, pagination is handled by the link

#     return all_courses

# def get_canvas_events(context_codes=[], start_date=datetime.now(), end_date=None, all_events=True):
#     headers = {'Authorization': f'Bearer {CANVAS_API_TOKEN}'}
#     page = 1
#     page_size = 100
#     params = {'per_page': page_size, "state[]":"available"}    

#     if context_codes:
#         params.setdefault('context_codes[]', []).append(context_codes)
    
#     # print("params",params)
#     if start_date or end_date:
#         if start_date:
#             if isinstance(start_date, datetime):
#                 start_date = start_date.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
#             params['start_date'] = start_date
#         # Default end_date to one year after start_date if not provided
#             if not end_date:
#                 dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
#                 end_date = (dt + timedelta(days=365)).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
#         if end_date:
#             if isinstance(end_date, datetime):
#                 end_date = end_date.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
#             params['end_date'] = end_date
#     else:
#         params['all_events'] = 'true'

#     url = f"{CANVAS_API_BASE}/calendar_events"
#     events = []
#     repeat = True

#     while repeat:
#         # print("page",page)
#         params['page'] = page  
#         response = requests.get(url, headers=headers, params=params)
#         # print(response)
#         if not response.ok:
#             # print(f"Canvas API error {response.status_code}: {response.text}")
#             break

#         data = response.json()
#         for event in data:
#             if 'start_at' in event:
#                 event['local_start_at'] = datetime.fromisoformat(event['start_at'].replace('Z', '+00:00')).astimezone(PACIFIC_TZ).strftime('%m/%d/%Y %I:%M %p')
#             if 'end_at' in event:
#                 event['local_end_at'] = datetime.fromisoformat(event['end_at'].replace('Z', '+00:00')).astimezone(PACIFIC_TZ).strftime('%m/%d/%Y %I:%M %p')
#             events.append(event)
#         # print("len",len(data))

#         if len(data) < page_size:
#             repeat = False

#         page += 1

#     return events

# def chunked_list(lst, n):
#     """Yield successive n-sized chunks from list."""
#     for i in range(0, len(lst), n):
#         yield lst[i:i + n]

# @bp.route('/terms')
# def get_canvas_enrollment_terms(account=""):
#     """
#     Fetches all enrollment terms for a given Canvas account using pagination.

#     Args:
#         account (str): Short code for account ("SSPPS", "HS", "SOM", etc.)

#     Returns:
#         list: List of term dictionaries.
#     """
#     if account == "HS":
#         accountID = HSAccountID
#     elif account == "SSPPS":
#         accountID = SSPPSAccountID
#     elif account == "SOM":
#         accountID = SOMAccountID
#     else:
#         accountID = mainAccountID

#     headers = {'Authorization': f'Bearer {CANVAS_API_TOKEN}'}
#     params = {'per_page': 100}
#     url = f"{CANVAS_API_BASE}/accounts/{accountID}/terms"
#     all_terms = []

#     while url:
#         response = requests.get(url, headers=headers, params=params)
#         response.raise_for_status()
#         data = response.json()
#         all_terms.extend(data.get("enrollment_terms", []))

#         # Parse the Link header for pagination
#         links = response.headers.get("Link", "")
#         next_url = None
#         for link in links.split(","):
#             if 'rel="next"' in link:
#                 next_url = link[link.find("<") + 1:link.find(">")]
#                 break
#         url = next_url
#         params = None  # Don't re-apply params after the first request

#     return all_terms

# def get_canvas_enrollments(course_id, enrollment_type="StudentEnrollment"):
#     """
#     Fetches all enrollments for a given Canvas course using pagination.

#     Args:
#         course_id (int): Canvas course ID.
#         enrollment_type (str): Type of enrollment to fetch (default is "StudentEnrollment").

#     Returns:
#         list: List of enrollment dictionaries.
#     """
#     headers = {'Authorization': f'Bearer {CANVAS_API_TOKEN}'}
#     params = {
#         'per_page': 100,
#         'type[]': enrollment_type,
#         'include[]': 'user'
#     }
#     url = f"{CANVAS_API_BASE}/courses/{course_id}/enrollments"
#     all_enrollments = []

#     while url:
#         response = requests.get(url, headers=headers, params=params)
#         response.raise_for_status()
#         all_enrollments.extend(response.json())

#         # Pagination via Link header
#         links = response.headers.get("Link", "")
#         next_url = None
#         for link in links.split(","):
#             if 'rel="next"' in link:
#                 next_url = link[link.find("<") + 1:link.find(">")]
#                 break
#         url = next_url
#         params = None  # Handled via next URL

#     return all_enrollments

@permission_required('panopto_scheduler+add, panopto_scheduler+edit')
@bp.route('/events')
def list_canvas_events():
    courses = get_canvas_courses()
    
    # Build a map from course ID to course info
    course_map = {
        f"course_{course['id']}": {
            "course_id": course['id'],
            "sis_course_id": course['sis_course_id'],
            "course_name": course.get('name', 'Unnamed Course'),
            "enrollment_term_id": course['enrollment_term_id'],
            "enrollment_term_name": course['term']['name'],
            "sis_term_id": course['term']['sis_term_id']
        }
        for course in courses if 'id' in course and course['term']['sis_term_id'] != "term_default"
    }
    course_ids = list(course_map.keys())

    events = []

    for course_chunk in chunked_list(course_ids, 10):
        course_events = get_canvas_events(course_chunk)
        for event in course_events:
            # Assume event has a 'context_code' like 'course_12345'
            course_info = course_map.get(event.get('context_code'))
            if course_info:
                # event['course_id'] = course_info['course_id']
                event['course_name'] = course_info['course_name']
                event['sis_course_id'] = course_info["sis_course_id"]
                event['term_id'] = course_info["enrollment_term_id"]
                event['session_title'] = event['sis_course_id']+" "+event['title']+" "+ datetime.fromisoformat(event['start_at'].replace('Z', '+00:00')).astimezone(PACIFIC_TZ).strftime('%#m/%#d/%Y')
            #     
        events.extend(course_events)

    # Sort events by 'start_at' (convert to datetime for robust sorting)
    events.sort(key=lambda e: datetime.fromisoformat(e['start_at'].replace('Z', '+00:00')) if e.get('start_at') else datetime.max)
  
    scheduled = ScheduledRecording.query.all()
    scheduled_map = { int(rec.canvas_event_id) : 
                        {"recorder_id": rec.recorder_id, 
                        "session_id": rec.panopto_session_id,
                        "folder_id": rec.folder_id,
                        "broadcast": rec.broadcast } for rec in scheduled }
    folders = get_panopto_folders()
    recorders = get_panopto_recorders()
    
    return render_template("scheduler/canvas_events.html", events=events, scheduled_map=scheduled_map, folders=folders, recorders=recorders)

@permission_required('panopto_scheduler+add, panopto_scheduler+edit')
@bp.route('/recordings/toggle', methods=['POST'])
def toggle_recording():
    data = request.form
    canvas_event_id = data['event_id']
    title = data['title']
    start_time = data['start_time']
    end_time = data['end_time']
    folder_id = data['folder_id']
    recorder_id = data['recorder_id']
    broadcast_str = data.get("broadcast", "false")
    broadcast = broadcast_str.lower() == "true"

    existing = ScheduledRecording.query.filter_by(canvas_event_id=canvas_event_id).first()

    if existing:
        if existing.panopto_session_id:
            delete_panopto_recording(existing.panopto_session_id)
        db.session.delete(existing)
        db.session.commit()
        # flash("Recording unscheduled", "info")
        return jsonify({"success": True, "message": "Recording unscheduled."})
    else:
        session_id = schedule_panopto_recording(title, start_time, end_time, folder_id, recorder_id, broadcast)
        if session_id:
            new_rec = ScheduledRecording(
                canvas_event_id=canvas_event_id,
                title=title,
                start_time=datetime.fromisoformat(start_time),
                end_time=datetime.fromisoformat(end_time),
                folder_id=folder_id,
                recorder_id=recorder_id,
                panopto_session_id=session_id,
                broadcast=broadcast
            )
            db.session.add(new_rec)
            db.session.commit()
            return jsonify({"success": True, "message": "Recording scheduled."})
            # flash("Recording scheduled", "success")
        else:
            return jsonify({"success": False, "message": "Failed to schedule."})
            # flash("Failed to schedule", "danger")

    # return redirect(url_for('scheduler.list_canvas_events'))

def schedule_panopto_recording(name, start_time, end_time, folder_id, recorder_id, broadcast):
    requests_session, oauth2, args = panopto_login()
    
    url = 'https://{0}/Panopto/api/v1/scheduledRecordings'.format(args.server)
    session_data = {
        "Name": name,
        "StartTime": start_time,
        "EndTime": end_time,
        "FolderId": folder_id,
        "Recorders": [
            {
                "RemoteRecorderId": recorder_id,
                "SuppressPrimary": False,
                "SuppressSecondary": False
            }
        ],
        "IsBroadcast": broadcast
    }
    params = {"resolveConflicts": False}
    headers = {'Content-type': 'application/json', 'Accept': 'application/json'}
    resp = requests_session.post(url=url, json=session_data, params=params, headers=headers)

    if inspect_response_is_unauthorized(resp):
        authorization(requests_session, oauth2)
        resp = requests_session.post(url=url, params=session_data)

    if resp.ok:
        return resp.json()['Id']

    return None

def delete_panopto_recording(session_id):
    requests_session, oauth2, args = panopto_login()
    
    url = 'https://{0}/Panopto/api/v1/scheduledRecordings/{1}'.format(args.server,session_id)
    resp = requests_session.delete(url=url)

    if inspect_response_is_unauthorized(resp):
        authorization(requests_session, oauth2)
        resp = requests_session.delete(url=url)

    return resp.ok
