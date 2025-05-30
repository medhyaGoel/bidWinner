import streamlit as st
from anthropic import Anthropic
import base64
import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import tempfile
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Initialize Claude client with API key from environment variables
client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# Set up Gmail API scopes
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

st.title("RFP Response Generator")

# Step 1: Upload PDF files
st.header("1. Upload Documents")
rfp_file = st.file_uploader("Upload RFP Document (PDF)", type="pdf")
profile_file = st.file_uploader("Upload Company Profile (PDF)", type="pdf")

# Session state to store our data
if 'requirements' not in st.session_state:
    st.session_state.requirements = []
if 'proposal' not in st.session_state:
    st.session_state.proposal = ""
if 'gmail_creds' not in st.session_state:
    st.session_state.gmail_creds = None
if 'rfp_updates' not in st.session_state:
    st.session_state.rfp_updates = []

# Step 2: Extract requirements with Claude
if rfp_file and profile_file and st.button("Extract Requirements"):
    with st.spinner("Claude is analyzing the RFP..."):
        # Save uploaded files to temporary files to pass to Claude
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_rfp:
            tmp_rfp.write(rfp_file.getvalue())
            rfp_path = tmp_rfp.name

        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_profile:
            tmp_profile.write(profile_file.getvalue())
            profile_path = tmp_profile.name

        try:
            # Upload files to Claude
            with open(rfp_path, "rb") as f:
                rfp_file_obj = client.beta.files.upload(
                    file=("rfp.pdf", f, "application/pdf")
                )

            with open(profile_path, "rb") as f:
                profile_file_obj = client.beta.files.upload(
                    file=("profile.pdf", f, "application/pdf")
                )

            # Create a message with the files
            response = client.beta.messages.create(  # Note: using beta.messages.create
                model="claude-sonnet-4-20250514",  # Using available model
                max_tokens=4000,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": """I've uploaded an RFP document and a company profile. Please extract all the requirements from the RFP 
                                            and list them in a numbered format. Focus on technical, business, and compliance requirements.

                                            Please provide a clear, numbered list of all requirements found in the RFP. Don't include anything else in your response other than the numbered list of requirements.
                                            """
                            },
                            {
                                "type": "document",
                                "source": {  # Correct nested structure
                                    "type": "file",
                                    "file_id": rfp_file_obj.id
                                }
                            },
                            {
                                "type": "document",
                                "source": {  # Correct nested structure
                                    "type": "file",
                                    "file_id": profile_file_obj.id
                                }
                            }
                        ]
                    }
                ],
                betas=["files-api-2025-04-14"],  # Important: including the beta flag
            )

            requirements_text = response.content[0].text
            # Convert the text to a list of requirements
            requirements_lines = [line.strip() for line in requirements_text.split('\n') if line.strip()]
            # Filter to keep only numbered lines
            # requirements = [line for line in requirements_lines if any(line.startswith(f"{i}.") for i in range(1, 100))]

            st.session_state.requirements = requirements_lines

        except Exception as e:
            st.error(f"Error analyzing documents: {str(e)}")
            st.error(f"Detailed error: {type(e).__name__}: {str(e)}")
        finally:
            # Clean up temporary files
            os.unlink(rfp_path)
            os.unlink(profile_path)

# Step 3: Allow editing of requirements
if st.session_state.requirements:
    st.header("2. Edit Requirements")

    # Create a text area for each requirement with a unique key
    updated_requirements = []
    for i, req in enumerate(st.session_state.requirements):
        updated_req = st.text_area(f"Requirement {i + 1}", req, key=f"req_{i}")
        updated_requirements.append(updated_req)

    # Button to update requirements
    if st.button("Update Requirements"):
        st.session_state.requirements = updated_requirements
        st.success("Requirements updated!")

# Step 4: Gmail integration for RFP updates
st.header("3. Check for RFP Updates in Gmail")


# Updated Gmail authentication function with manual process
def gmail_authenticate():
    # Initialize session state if needed
    if 'auth_flow' not in st.session_state:
        st.session_state.auth_flow = None
    if 'auth_step' not in st.session_state:
        st.session_state.auth_step = 'start'

    # Check for existing credentials
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        if creds and creds.valid:
            return creds

    # Handle credential refresh
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
        return creds

    # Start of authentication flow
    if st.session_state.auth_step == 'start':
        st.markdown("### Gmail Authentication")
        st.markdown("You need to authenticate with your Gmail account to use this feature.")

        if st.button("Start Authentication Process"):
            # Create a new flow
            st.session_state.auth_flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json',
                SCOPES
            )
            # Generate auth URL with explicit scopes
            auth_url, _ = st.session_state.auth_flow.authorization_url(
                access_type='offline',
                include_granted_scopes='true',
                prompt='consent'
            )
            st.session_state.auth_url = auth_url
            st.session_state.auth_step = 'get_code'
            st.experimental_rerun()

    # Step to get authorization code
    elif st.session_state.auth_step == 'get_code':
        st.markdown("### Gmail Authentication")
        st.markdown("1. Copy the URL below")
        st.code(st.session_state.auth_url)
        st.markdown("2. Open it in a new browser window/tab")
        st.markdown("3. Sign in with your RFP Gmail account")
        st.markdown("4. After approval, you'll be redirected")
        st.markdown("5. Copy the entire redirected URL")

        redirect_url = st.text_input("Paste the entire redirected URL here:")

        if redirect_url:
            try:
                # Extract the authorization code from the URL
                code = redirect_url.split('code=')[1].split('&')[0]

                # Exchange code for token
                token = st.session_state.auth_flow.fetch_token(code=code)
                creds = st.session_state.auth_flow.credentials

                # Save the credentials
                with open('token.json', 'w') as token_file:
                    token_file.write(creds.to_json())

                st.session_state.auth_step = 'complete'
                st.success("Successfully authenticated!")
                st.experimental_rerun()
            except Exception as e:
                st.error(f"Authentication error: {str(e)}")

    # Authentication complete
    elif st.session_state.auth_step == 'complete':
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)

    return creds


if st.button("Connect to Gmail"):
    st.session_state.gmail_creds = gmail_authenticate()

if st.session_state.gmail_creds and st.button("Check for RFP Updates"):
    with st.spinner("Checking Gmail for RFP updates..."):
        try:
            service = build('gmail', 'v1', credentials=st.session_state.gmail_creds)
            results = service.users().messages().list(userId='me', q="subject:RFP OR subject:proposal").execute()
            messages = results.get('messages', [])

            if not messages:
                st.info("No RFP-related emails found.")
            else:
                updates = []
                for message in messages[:5]:  # Limit to 5 most recent emails
                    msg = service.users().messages().get(userId='me', id=message['id']).execute()
                    payload = msg['payload']
                    headers = payload['headers']

                    subject = next((header['value'] for header in headers if header['name'] == 'Subject'), 'No Subject')
                    snippet = msg['snippet']

                    updates.append(f"Subject: {subject}\nPreview: {snippet}")

                st.session_state.rfp_updates = updates
        except Exception as e:
            st.error(f"Error checking Gmail: {str(e)}")

if st.session_state.rfp_updates:
    for i, update in enumerate(st.session_state.rfp_updates):
        st.text_area(f"Email {i + 1}", update, height=100, key=f"email_{i}")

# Step 5: Generate proposal
st.header("4. Generate Proposal")

if st.session_state.requirements and st.button("Generate Proposal"):
    with st.spinner("Claude is generating your proposal..."):
        # Prepare requirements text
        requirements_text = "\n".join(st.session_state.requirements)

        try:
            response = client.messages.create(
                model="claude-3-opus-20240229",
                max_tokens=4000,
                messages=[
                    {
                        "role": "user",
                        "content": f"""
                        Please generate a professional proposal based on these RFP requirements:

                        {requirements_text}

                        Create a complete proposal that addresses all the requirements. Include:
                        1. Executive Summary
                        2. Company Introduction
                        3. Understanding of Requirements
                        4. Proposed Solution
                        5. Implementation Plan
                        6. Pricing (use placeholder pricing)
                        7. Conclusion

                        Format it professionally.
                        """
                    }
                ]
            )

            st.session_state.proposal = response.content[0].text

        except Exception as e:
            st.error(f"Error generating proposal: {str(e)}")

# Display and allow editing of the generated proposal
if st.session_state.proposal:
    st.header("5. Edit and Download Proposal")
    edited_proposal = st.text_area("Edit Proposal", st.session_state.proposal, height=500)

    if edited_proposal != st.session_state.proposal:
        st.session_state.proposal = edited_proposal

    # Download button for the proposal
    if st.button("Download Proposal"):
        b64 = base64.b64encode(st.session_state.proposal.encode()).decode()
        href = f'<a href="data:file/txt;base64,{b64}" download="proposal.txt">Download proposal as text file</a>'
        st.markdown(href, unsafe_allow_html=True)

st.sidebar.header("Instructions")
st.sidebar.write("""
1. Upload your RFP document and company profile
2. Click 'Extract Requirements' to analyze with Claude
3. Review and edit the requirements
4. Connect to Gmail to check for updates
5. Generate and customize your proposal
6. Download the final proposal
""")
