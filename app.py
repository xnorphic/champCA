import streamlit as st
import json
import tempfile
import os
import openai
import re
from google.oauth2 import service_account
from googleapiclient.discovery import build

# --- Sidebar Setup ---
st.set_page_config(page_title="Company Data Chat", layout="wide")
st.sidebar.title("🔐 Auth & Setup")

# --- Step 1: Authentication with Google Drive API ---
def authenticate_drive():
    try:
        # Load service account JSON from Streamlit secrets
        service_account_info = st.secrets["google"]["service_account_json"]
        
        # If service_account_info is a string, parse it
        if isinstance(service_account_info, str):
            try:
                # Replace escaped newlines with actual newlines
                service_account_info = service_account_info.replace('\\n', '\n')
                # Remove any control characters
                service_account_info = re.sub(r'[\x00-\x1F\x7F]', '', service_account_info)
                service_account_dict = json.loads(service_account_info)
            except json.JSONDecodeError as e:
                st.error(f"Failed to parse service account JSON: {str(e)}")
                return None
        else:
            service_account_dict = service_account_info
        
        # Create credentials with google-auth
        credentials = service_account.Credentials.from_service_account_info(
            service_account_dict,
            scopes=['https://www.googleapis.com/auth/drive']
        )
        
        # Build the Drive API client
        drive_service = build('drive', 'v3', credentials=credentials)
        return drive_service
            
    except Exception as e:
        st.error(f"Authentication error: {str(e)}")
        st.info("Please check your service account credentials in Streamlit secrets.")
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

# --- Step 4: Get file metadata ---
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

# --- Main UI ---
st.title("📊 Company Data Comparison Chat")

# Authentication
drive_service = authenticate_drive()

if drive_service is None:
    st.error("Failed to authenticate with Google Drive. Please check your configuration.")
    
    # Provide troubleshooting help
    st.markdown("""
    ### Troubleshooting:
    1. Check your service account JSON in secrets.toml for formatting issues
    2. Make sure the service account has proper access to the Google Drive folder
    3. Try creating a new service account with the necessary permissions
    4. Verify that the Google Drive API is enabled for your project
    """)
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
