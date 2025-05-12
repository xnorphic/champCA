import streamlit as st
from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive
import json
import tempfile
import os
import openai

# --- Sidebar Setup ---
st.set_page_config(page_title="Company Data Chat", layout="wide")
st.sidebar.title("🔐 Auth & Setup")

# --- Step 1: Save secret to temp file ---
def save_client_secret():
    secret_json_str = st.secrets["client_secret_json"]
    temp_path = os.path.join(tempfile.gettempdir(), "client_secret.json")
    with open(temp_path, "w") as f:
        json.dump(json.loads(secret_json_str), f)
    return temp_path

# --- Step 2: Authenticate with Google Drive ---
@st.cache_resource
def authenticate_drive():
    path = save_client_secret()
    gauth = GoogleAuth()
    gauth.LoadClientConfigFile(path)
    gauth.LocalWebserverAuth()
    drive = GoogleDrive(gauth)
    return drive

# --- Step 3: Load company subfolders ---
def get_company_folders(drive, parent_folder_id):
    folder_list = drive.ListFile({
        'q': f"'{parent_folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
    }).GetList()
    return {folder['title']: folder['id'] for folder in folder_list}

# --- Step 4: Load files from company folder ---
def load_files_from_folder(drive, folder_id):
    file_list = drive.ListFile({
        'q': f"'{folder_id}' in parents and trashed=false"
    }).GetList()
    return {f['title']: f.GetContentString() for f in file_list}

# --- Step 5: GPT-4.1-Nano Interaction ---
def ask_gpt(context, query):
    openai.api_key = st.secrets["openai_api_key"]
    response = openai.ChatCompletion.create(
        model="gpt-4.1-nano-2025-04-14",
        messages=[
            {"role": "system", "content": "You are an analyst comparing companies."},
            {"role": "user", "content": context},
            {"role": "user", "content": query}
        ]
    )
    return response.choices[0].message["content"]

# --- Main UI ---
st.title("📊 Company Data Comparison Chat")
drive = authenticate_drive()
parent_folder_id = "1lQ536qAHRUTt7OT3cd5qzo2RwgL5UgjB"

company_folders = get_company_folders(drive, parent_folder_id)
selected_companies = st.multiselect("Select companies to compare", list(company_folders.keys()))

if selected_companies:
    combined_context = ""
    for company in selected_companies:
        st.subheader(f"📁 {company}")
        files = load_files_from_folder(drive, company_folders[company])
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
