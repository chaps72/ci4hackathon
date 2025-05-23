
import streamlit as st
import pandas as pd

# ---- Title ----
st.set_page_config(page_title="Trial & Sample Finder", layout="wide")
st.title("🔬 Real-Time Trial & Sample Finder")
st.markdown("Search and filter open clinical trials and available biospecimens at your cancer center.")

# ---- Sidebar Filters ----
st.sidebar.header("Filter Options")
tumor_type = st.sidebar.multiselect("Tumor Type", options=[], default=[])
trial_phase = st.sidebar.multiselect("Trial Phase", options=[], default=[])
sample_type = st.sidebar.multiselect("Sample Type", options=[], default=[])
data_available = st.sidebar.multiselect("Data Available", options=[], default=[])

# ---- File Upload or Load Sample Data ----
st.sidebar.write("---")
uploaded_file = st.sidebar.file_uploader("Upload Trial & Sample Dataset (CSV)", type=["csv"])

if uploaded_file:
    df = pd.read_csv(uploaded_file)
else:
    # Sample data if no file is uploaded
    df = pd.DataFrame({
        "Trial ID": ["NCT001", "NCT002", "NCT003"],
        "Title": ["Immunotherapy in NSCLC", "Targeted Therapy in Breast Cancer", "Lung Cancer Biobank"],
        "Tumor Type": ["Lung", "Breast", "Lung"],
        "Phase": ["II", "III", "N/A"],
        "Sample Type": ["Tumor", "Blood", "Tumor"],
        "Data Available": ["RNAseq", "Clinical", "RNAseq, Clinical"],
        "PI": ["Dr. Smith", "Dr. Lee", "Dr. Patel"],
        "Contact": ["smith@email.com", "lee@email.com", "patel@email.com"]
    })

    st.info("Using sample data. Upload your own CSV for real-time information.")

# ---- Populate filter options ----
st.session_state.tumor_list = df["Tumor Type"].dropna().unique().tolist()
st.session_state.phase_list = df["Phase"].dropna().unique().tolist()
st.session_state.sample_list = df["Sample Type"].dropna().unique().tolist()
st.session_state.data_list = sorted(set(
    sum([x.split(", ") for x in df["Data Available"].dropna()], [])
))

# Update sidebar widgets with dynamic values
if not tumor_type:
    tumor_type = st.sidebar.multiselect("Tumor Type", options=st.session_state.tumor_list)
if not trial_phase:
    trial_phase = st.sidebar.multiselect("Trial Phase", options=st.session_state.phase_list)
if not sample_type:
    sample_type = st.sidebar.multiselect("Sample Type", options=st.session_state.sample_list)
if not data_available:
    data_available = st.sidebar.multiselect("Data Available", options=st.session_state.data_list)

# ---- Filtering ----
filtered_df = df[
    df["Tumor Type"].isin(tumor_type) &
    df["Phase"].isin(trial_phase) &
    df["Sample Type"].isin(sample_type) &
    df["Data Available"].apply(lambda x: any(d in x for d in data_available))
]

# ---- Results ----
st.subheader(f"Showing {len(filtered_df)} matching trials and sample collections")
st.dataframe(filtered_df, use_container_width=True)

# ---- Request Form ----
st.write("---")
st.subheader("📩 Express Interest or Request Access")
with st.form("request_form"):
    name = st.text_input("Your Name")
    email = st.text_input("Your Email")
    trial_id = st.selectbox("Trial of Interest", options=filtered_df["Trial ID"] if not filtered_df.empty else [])
    message = st.text_area("Message")
    submitted = st.form_submit_button("Submit")

    if submitted:
        st.success("Your request has been submitted. The study team will contact you shortly.")

