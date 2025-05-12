import streamlit as st
from pydrive2.auth import ServiceAccountAuth
from pydrive2.drive import GoogleDrive
import json
import tempfile
import os
import openai

# Streamlit setup
st.set_page_config(page_title="Company Data Chat", layout="wide")
st.sidebar.title("🔐 Auth & Setup")

# Step 1: Save service account JSON to temp file
def save_service_account():
    sa_json = st.secrets["google"]["service_account_json"]
    path = os.path.join(tempfile.gettempdir(), "service_account.json")
    with open(path, "w") as f:
        json.dump(json.loads(sa_json), f)
    return path

# Step 2: Authenticate with PyDrive2 using service account
@st.cache_resource
def authenticate_drive():
    path = save_service_account()
    gauth = ServiceAccountAuth()
    gauth.LoadServiceConfigFile(path)
    gauth.Authorize()
    drive = GoogleDrive(gauth)
    return drive

# Step 3: Get subfolders (companies)
def get_company_folders(drive, parent_folder_id):
    folder_list = drive.ListFile({
        'q': f"'{parent_folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
    }).GetList()
    return {folder['title']: folder['id'] for folder in folder_list}

# Step 4: Load files from a folder
def load_files_from_folder(drive, folder_id):
    file_list = drive.ListFile({
        'q': f"'{folder_id}' in parents and trashed=false"
    }).GetList()
    return {f['title']: f.GetContentString() for f in file_list}

# Step 5: Ask GPT-4
def ask_gpt(context, query):
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

    st.markdown("---")
    st.subheader("💬 Ask questions about the selected companies")
    user_query = st.text_input("Ask your question:")
    if user_query:
        with st.spinner("Thinking..."):
            answer = ask_gpt(combined_context, user_query)
            st.success(answer)
else:
    st.info("Please select at least one company to begin.")
