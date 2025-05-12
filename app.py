import streamlit as st
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
import json
import tempfile
import os
import openai

# --- Sidebar Setup ---
st.set_page_config(page_title="Company Data Chat", layout="wide")
st.sidebar.title("🔐 Auth & Setup")

# --- Step 1: Save service account credentials to temp file ---
def save_service_account_credentials():
    try:
        # Load service account JSON from Streamlit secrets using the correct key name
        service_account_info = st.secrets["google"]["service_account_json"]  # Changed from service_account to service_account_json
        
        # Create temp file
        temp_path = os.path.join(tempfile.gettempdir(), "service_account.json")
        
        # If service_account_info is already a string, parse it
        if isinstance(service_account_info, str):
            service_account_info = json.loads(service_account_info)
            
        # Write to temp file
        with open(temp_path, "w") as f:
            json.dump(service_account_info, f)
            
        return temp_path
    except Exception as e:
        st.error(f"Error saving credentials: {str(e)}")
        raise

# --- Step 2: Authenticate with Google Drive using service account ---
@st.cache_resource
def authenticate_drive():
    try:
        credentials_path = save_service_account_credentials()
        
        settings = {
            "client_config_backend": "service",
            "service_config": {
                "client_json_file_path": credentials_path
            }
        }
        
        gauth = GoogleAuth(settings=settings)
        gauth.ServiceAuth()
        drive = GoogleDrive(gauth)
        return drive
    except Exception as e:
        st.error(f"Authentication error: {str(e)}")
        st.info("Please check your service account credentials in Streamlit secrets.")
        return None

# --- Step 3: Load company subfolders ---
def get_company_folders(drive, parent_folder_id):
    try:
        folder_list = drive.ListFile({
            'q': f"'{parent_folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
        }).GetList()
        return {folder['title']: folder['id'] for folder in folder_list}
    except Exception as e:
        st.error(f"Error loading company folders: {str(e)}")
        return {}

# --- Step 4: Load files from company folder ---
def load_files_from_folder(drive, folder_id):
    try:
        file_list = drive.ListFile({
            'q': f"'{folder_id}' in parents and trashed=false"
        }).GetList()
        return {f['title']: f.GetContentString() for f in file_list}
    except Exception as e:
        st.error(f"Error loading files: {str(e)}")
        return {}

# --- Step 5: GPT-4.1-Nano Interaction ---
def ask_gpt(context, query):
    try:
        # Load OpenAI API key from Streamlit secrets
        openai.api_key = st.secrets["openai"]["api_key"]
        
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

# Authenticate and list company folders
drive = authenticate_drive()

if drive is None:
    st.error("Failed to authenticate with Google Drive. Please check your configuration.")
else:
    parent_folder_id = "1lQ536qAHRUTt7OT3cd5qzo2RwgL5UgjB"  # Google Drive folder ID
    company_folders = get_company_folders(drive, parent_folder_id)
    
    if not company_folders:
        st.warning("No company folders found. Please check the parent folder ID.")
    else:
        selected_companies = st.multiselect("Select companies to compare", list(company_folders.keys()))
        
        if selected_companies:
            combined_context = ""
            for company in selected_companies:
                st.subheader(f"📁 {company}")
                files = load_files_from_folder(drive, company_folders[company])
                
                if not files:
                    st.warning(f"No files found for {company}.")
                else:
                    for fname, content in files.items():
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
