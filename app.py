import streamlit as st
import json
import os
import openai
import re
import tempfile
import io
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# Try to import PyPDF2 for PDF extraction
try:
    import PyPDF2
    HAS_PYPDF2 = True
except ImportError:
    HAS_PYPDF2 = False

# --- Sidebar Setup ---
st.set_page_config(page_title="Company Data Chat", layout="wide")
st.sidebar.title("🔐 Auth & Setup")

# --- Debugging Helpers ---
def debug_secrets():
    """Helper function to debug secrets without exposing sensitive data"""
    try:
        # Check if google section exists
        if "google" in st.secrets:
            st.sidebar.success("✅ 'google' section found in secrets")
            
            # Check if service_account_json exists
            if "service_account_json" in st.secrets["google"]:
                sa_info = st.secrets["google"]["service_account_json"]
                if isinstance(sa_info, str):
                    st.sidebar.success(f"✅ 'service_account_json' found (type: string, length: {len(sa_info)})")
                    
                    # Check if it looks like a valid JSON
                    if sa_info.strip().startswith("{") and sa_info.strip().endswith("}"):
                        st.sidebar.success("✅ Credential string appears to be JSON-formatted")
                    else:
                        st.sidebar.error("❌ Credential string does not appear to be JSON-formatted")
                else:
                    st.sidebar.success(f"✅ 'service_account_json' found (type: {type(sa_info).__name__})")
            else:
                st.sidebar.error("❌ 'service_account_json' not found in google section")
                
            # Check what keys are available
            keys = list(st.secrets["google"].keys())
            st.sidebar.info(f"Available keys in google section: {', '.join(keys)}")
        else:
            st.sidebar.error("❌ 'google' section not found in secrets")
            
        # Check if openai section exists
        if "openai" in st.secrets:
            st.sidebar.success("✅ 'openai' section found in secrets")
            if "api_key" in st.secrets["openai"]:
                api_key = st.secrets["openai"]["api_key"]
                st.sidebar.success(f"✅ OpenAI API key found (length: {len(api_key)})")
            else:
                st.sidebar.error("❌ 'api_key' not found in openai section")
        else:
            st.sidebar.error("❌ 'openai' section not found in secrets")
            
    except Exception as e:
        st.sidebar.error(f"Error debugging secrets: {str(e)}")

# --- Function to extract PDF content ---
def extract_pdf_content(drive_service, file_id):
    if not HAS_PYPDF2:
        return "[PDF extraction requires PyPDF2 library. Add 'PyPDF2' to your requirements.txt.]"
        
    try:
        request = drive_service.files().get_media(fileId=file_id)
        file_content = io.BytesIO()
        downloader = MediaIoBaseDownload(file_content, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
        
        file_content.seek(0)
        pdf_reader = PyPDF2.PdfReader(file_content)
        
        # Extract text from all pages
        text = ""
        for page_num in range(len(pdf_reader.pages)):
            text += pdf_reader.pages[page_num].extract_text() + "\n\n"
        
        return text
    except Exception as e:
        return f"[Error extracting PDF content: {str(e)}]"

# --- Step 1: Authentication with Google Drive API ---
def authenticate_drive():
    try:
        # Check if we have the google section in secrets
        if "google" not in st.secrets:
            st.error("No 'google' section found in secrets.")
            return None
            
        # Check which keys are available
        available_keys = list(st.secrets["google"].keys())
        
        # Try different possible keys for service account info
        service_account_info = None
        possible_keys = ["service_account_json", "service_account", "credentials", "auth"]
        
        for key in possible_keys:
            if key in st.secrets["google"]:
                service_account_info = st.secrets["google"][key]
                st.success(f"Found credentials using key: {key}")
                break
                
        if service_account_info is None:
            st.error(f"No service account credentials found. Available keys: {', '.join(available_keys)}")
            return None
        
        # Create a temporary file to store the credentials
        temp_creds_path = os.path.join(tempfile.gettempdir(), "google_creds.json")
        
        # If service_account_info is a string, save it to the temp file
        if isinstance(service_account_info, str):
            # Clean up the JSON string
            service_account_info = service_account_info.replace('\\n', '\n')
            service_account_info = re.sub(r'[\x00-\x1F\x7F]', '', service_account_info)
            
            try:
                # Try to parse it as JSON
                creds_dict = json.loads(service_account_info)
                
                # Write cleaned JSON to temp file
                with open(temp_creds_path, 'w') as f:
                    json.dump(creds_dict, f)
                    
                # Use the file for authentication
                credentials = service_account.Credentials.from_service_account_file(
                    temp_creds_path, 
                    scopes=['https://www.googleapis.com/auth/drive']
                )
            except json.JSONDecodeError as e:
                st.error(f"Invalid JSON in service account credentials: {str(e)}")
                return None
        else:
            # If it's already a dict, use it directly
            try:
                with open(temp_creds_path, 'w') as f:
                    json.dump(service_account_info, f)
                    
                credentials = service_account.Credentials.from_service_account_file(
                    temp_creds_path, 
                    scopes=['https://www.googleapis.com/auth/drive']
                )
            except Exception as e:
                st.error(f"Error writing credentials to file: {str(e)}")
                return None
        
        # Build the Drive API client
        drive_service = build('drive', 'v3', credentials=credentials)
        st.success("Successfully authenticated with Google Drive!")
        return drive_service
            
    except Exception as e:
        st.error(f"Authentication error: {str(e)}")
        return None

# --- Step 2: Get company folders using Drive API ---
def get_company_folders(drive_service, parent_folder_id):
    try:
        results = drive_service.files().list(
            q=f"'{parent_folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
            fields="files(id, name)"
        ).execute()
        
        folders = results.get('files', [])
        return {folder['name']: folder['id'] for folder in folders}
    except Exception as e:
        st.error(f"Error loading company folders: {str(e)}")
        return {}

# --- Step 3: List files in a folder ---
def list_files_in_folder(drive_service, folder_id):
    try:
        results = drive_service.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            fields="files(id, name, mimeType, size)"
        ).execute()
        
        files = results.get('files', [])
        return files
    except Exception as e:
        st.error(f"Error listing files: {str(e)}")
        return []

# --- Step 4: Get file metadata and content ---
def get_file_info(drive_service, files):
    result = {}
    
    for file in files:
        try:
            file_id = file['id']
            file_name = file['name']
            mime_type = file.get('mimeType', 'unknown')
            
            # Handle different file types
            if 'application/vnd.google-apps.' in mime_type:
                # Google Workspace files
                if mime_type == 'application/vnd.google-apps.document':
                    file_info = f"[Google Doc: {file_name}]"
                elif mime_type == 'application/vnd.google-apps.spreadsheet':
                    file_info = f"[Google Sheet: {file_name}]"
                elif mime_type == 'application/vnd.google-apps.presentation':
                    file_info = f"[Google Slides: {file_name}]"
                else:
                    file_info = f"[Google Workspace file: {file_name}]"
            elif mime_type == 'application/pdf':
                # Extract content from PDF
                file_info = extract_pdf_content(drive_service, file_id)
            else:
                # For regular files, just show metadata
                size = file.get('size', 'unknown size')
                ext = os.path.splitext(file_name)[1].lower()
                file_info = f"[File: {file_name}, Type: {mime_type}, Extension: {ext}]"
                
            result[file_name] = file_info
            
        except Exception as e:
            st.warning(f"Error processing file {file.get('name', 'unknown')}: {str(e)}")
            result[file.get('name', f'Unknown file')] = f"[Error: {str(e)}]"
    
    return result

# --- Step 5: GPT Interaction ---
def ask_gpt(context, query):
    try:
        # Load OpenAI API key from Streamlit secrets
        openai.api_key = st.secrets["openai"]["api_key"]
        
        # Truncate context if it's too long
        max_context_length = 16000
        if len(context) > max_context_length:
            st.warning(f"Context is too large ({len(context)} chars). Truncating to {max_context_length} chars.")
            context = context[:max_context_length] + "\n\n[Note: Context was truncated due to size limits]"
        
        # Support both v1 and pre-v1 OpenAI API
        try:
            # Try v1 API
            response = openai.chat.completions.create(
                model="gpt-4.1-nano-2025-04-14",
                messages=[
                    {"role": "system", "content": "You are an analyst comparing companies."},
                    {"role": "user", "content": context},
                    {"role": "user", "content": query}
                ]
            )
            return response.choices[0].message.content
        except AttributeError:
            # Fall back to pre-v1 API
            response = openai.ChatCompletion.create(
                model="gpt-4.1-nano-2025-04-14",
                messages=[
                    {"role": "system", "content": "You are an analyst comparing companies."},
                    {"role": "user", "content": context},
                    {"role": "user", "content": query}
                ]
            )
            return response.choices[0].message["content"]
    except Exception as e:
        st.error(f"Error calling OpenAI API: {str(e)}")
        return "Sorry, I encountered an error while processing your question."

# --- Manual Data Input Function ---
def add_manual_data():
    st.subheader("Add Manual Financial Data")
    
    with st.form("manual_data_form"):
        company = st.text_input("Company Name")
        metric = st.text_input("Metric (e.g., Revenue, Net Profit)")
        fy22 = st.text_input("FY22 Value")
        fy23 = st.text_input("FY23 Value")
        
        submit = st.form_submit_button("Add Data")
        
        if submit and company and metric:
            data = f"{metric} FY22: {fy22}\n{metric} FY23: {fy23}\n"
            return company, data
    
    return None, None

# --- Main UI ---
st.title("📊 Company Data Comparison Chat")

# Debug the secrets (doesn't expose sensitive data)
debug_secrets()

# Add option for manual data input
show_manual_input = st.sidebar.checkbox("Add manual financial data")

# Authentication
drive_service = authenticate_drive()

if drive_service is None:
    st.error("Failed to authenticate with Google Drive. Please check your configuration.")
    
    # Manual credentials input option
    st.subheader("Manual Authentication")
    st.markdown("""
    If you're having trouble with secrets.toml, you can upload your service account JSON file directly:
    """)
    
    uploaded_file = st.file_uploader("Upload service account JSON file", type=["json"])
    
    if uploaded_file is not None:
        try:
            # Save the uploaded file to a temporary location
            temp_path = os.path.join(tempfile.gettempdir(), "uploaded_creds.json")
            with open(temp_path, "wb") as f:
                f.write(uploaded_file.getvalue())
            
            # Create credentials from the file
            credentials = service_account.Credentials.from_service_account_file(
                temp_path,
                scopes=['https://www.googleapis.com/auth/drive']
            )
            
            # Build the Drive API client
            drive_service = build('drive', 'v3', credentials=credentials)
            st.success("Successfully authenticated with the uploaded credentials!")
            
            # Continue with the rest of the app...
            # Parent folder ID
            parent_folder_id = "1lQ536qAHRUTt7OT3cd5qzo2RwgL5UgjB"
            company_folders = get_company_folders(drive_service, parent_folder_id)
            
            if not company_folders:
                st.warning("No company folders found. Please check the parent folder ID.")
            else:
                # Process company folders just like in the main flow
                selected_companies = st.multiselect("Select companies to compare", list(company_folders.keys()))
                
                if selected_companies:
                    combined_context = ""
                    for company in selected_companies:
                        st.subheader(f"📁 {company}")
                        folder_id = company_folders[company]
                        
                        # List files in the folder
                        files_list = list_files_in_folder(drive_service, folder_id)
                        
                        if not files_list:
                            st.warning(f"No files found for {company}.")
                        else:
                            # Get file info
                            files_info = get_file_info(drive_service, files_list)
                            
                            for fname, content in files_info.items():
                                with st.expander(f"📄 {fname}"):
                                    st.text_area("File Content", value=content, height=200, key=f"{company}_{fname}")
                                combined_context += f"\n\n[{company} - {fname}]:\n{content}"
                    
                    # Manual data input option
                    if show_manual_input:
                        manual_company, manual_data = add_manual_data()
                        if manual_company and manual_data:
                            combined_context += f"\n\n[{manual_company} - Manual Data]:\n{manual_data}"
                            st.success(f"Added manual data for {manual_company}")
                    
                    # Chat Interface
                    st.markdown("---")
                    st.subheader("💬 Ask questions about the selected companies")
                    user_query = st.text_input("Ask your question:")
                    
                    if user_query:
                        with st.spinner("Thinking..."):
                            answer = ask_gpt(combined_context, user_query)
                            st.success(answer)
                else:
                    st.info("Please select at least one company to begin.")
        except Exception as e:
            st.error(f"Error with uploaded credentials: {str(e)}")
else:
    # Parent folder ID
    parent_folder_id = "1lQ536qAHRUTt7OT3cd5qzo2RwgL5UgjB"
    company_folders = get_company_folders(drive_service, parent_folder_id)
    
    if not company_folders:
        st.warning("No company folders found. Please check the parent folder ID.")
    else:
        selected_companies = st.multiselect("Select companies to compare", list(company_folders.keys()))
        
        if selected_companies:
            combined_context = ""
            for company in selected_companies:
                st.subheader(f"📁 {company}")
                folder_id = company_folders[company]
                
                # List files in the folder
                files_list = list_files_in_folder(drive_service, folder_id)
                
                if not files_list:
                    st.warning(f"No files found for {company}.")
                else:
                    # Get file info
                    files_info = get_file_info(drive_service, files_list)
                    
                    for fname, content in files_info.items():
                        with st.expander(f"📄 {fname}"):
                            st.text_area("File Content", value=content, height=200, key=f"{company}_{fname}")
                        combined_context += f"\n\n[{company} - {fname}]:\n{content}"
            
            # Manual data input option
            if show_manual_input:
                manual_company, manual_data = add_manual_data()
                if manual_company and manual_data:
                    combined_context += f"\n\n[{manual_company} - Manual Data]:\n{manual_data}"
                    st.success(f"Added manual data for {manual_company}")
            
            # Chat Interface
            st.markdown("---")
            st.subheader("💬 Ask questions about the selected companies")
            user_query = st.text_input("Ask your question:")
            
            if user_query:
                with st.spinner("Thinking..."):
                    answer = ask_gpt(combined_context, user_query)
                    st.success(answer)
        else:
            st.info("Please select at least one company to begin.")
