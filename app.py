from dotenv import load_dotenv
load_dotenv()  # This loads the .env file you just created
import streamlit as st
import pandas as pd
import os
import time

# --- 1. SMART DATABASE CONNECTION ---
DATABASE_URL = None
if "DATABASE_URL" in os.environ:
    DATABASE_URL = os.environ["DATABASE_URL"]
elif hasattr(st, "secrets") and "DATABASE_URL" in st.secrets:
    DATABASE_URL = st.secrets["DATABASE_URL"]

if DATABASE_URL:
    import psycopg2
    DB_TYPE = "POSTGRES"
else:
    import sqlite3
    DB_TYPE = "SQLITE"
    DB_FILE = "obe_system_v18.db"

# --- 2. CONFIGURATION ---
st.set_page_config(page_title="OBE Compliance Portal", layout="wide", page_icon="🎓")
ADMIN_PASSWORD = "123"

# LISTS
PLOS = [f"PLO-{i}" for i in range(1, 13)]
BLOOMS = ([f"C{i}" for i in range(1, 7)] + [f"P{i}" for i in range(1, 8)] + [f"A{i}" for i in range(1, 6)])
WKS = [f"WK{i}" for i in range(1, 9)]
SDGS = [f"SDG-{i}" for i in range(1, 18)]
ECS = [f"EC{i}" for i in range(1, 8)]

# --- 3. DARK CSS ---
st.markdown("""
<style>
    .stApp { background-color: #0e1117; color: #fafafa; }
    [data-testid="stSidebar"] { background-color: #262730; border-right: 1px solid #41444b; }
    .stDataFrame th { background-color: #262730 !important; color: white !important; font-weight: bold; }
    .stDataFrame td { background-color: #1a1c24 !important; color: #e0e0e0 !important; }
    .stSelectbox div[data-baseweb="select"], .stTextInput input, .stTextArea textarea {
        background-color: #1a1c24 !important; color: white !important; border: 1px solid #444 !important;
    }
</style>
""", unsafe_allow_html=True)

# --- 4. DATABASE ENGINE ---
def get_db_connection():
    if DB_TYPE == "POSTGRES":
        return psycopg2.connect(DATABASE_URL, sslmode='require')
    else:
        return sqlite3.connect(DB_FILE, check_same_thread=False)

def run_query(query, params=(), fetch=False):
    conn = get_db_connection()
    c = conn.cursor()
    if DB_TYPE == "POSTGRES":
        query = query.replace("?", "%s")
        query = query.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
        query = query.replace("DATETIME DEFAULT CURRENT_TIMESTAMP", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    try:
        c.execute(query, params)
        if fetch:
            if c.description:
                cols = [desc[0] for desc in c.description]
                result = pd.DataFrame(c.fetchall(), columns=cols)
            else: result = pd.DataFrame()
        else:
            conn.commit()
            result = None
    except Exception as e:
        st.error(f"Database Error: {e}")
        result = None
    finally:
        conn.close()
    return result

def init_db():
    run_query('''CREATE TABLE IF NOT EXISTS inventory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    course_code TEXT,
                    subject TEXT,
                    theory_lab TEXT,
                    credit_hours TEXT,
                    clo_id TEXT,
                    statement TEXT,
                    plo TEXT,
                    bloom TEXT,
                    kp TEXT,
                    sgds TEXT,
                    ec TEXT,
                    notes TEXT
                )''')
    run_query('''CREATE TABLE IF NOT EXISTS drafts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    inv_id INTEGER,
                    course_code TEXT,
                    subject TEXT,
                    clo_id TEXT,
                    new_statement TEXT,
                    new_plo TEXT,
                    new_bloom TEXT,
                    new_kp TEXT,
                    new_sgds TEXT,
                    new_ec TEXT,
                    new_theory_lab TEXT,
                    new_credit_hours TEXT,
                    new_notes TEXT,
                    request_type TEXT,
                    requester TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )''')

# --- 5. PARSER ---
def smart_parse_file(uploaded_file):
    try:
        if uploaded_file.name.endswith('.csv'):
            df = pd.read_csv(uploaded_file)
            if not any("course" in str(c).lower() for c in df.columns):
                uploaded_file.seek(0)
                df = pd.read_csv(uploaded_file, header=1)
        else:
            df = pd.read_excel(uploaded_file)
            if not any("course" in str(c).lower() for c in df.columns):
                df = pd.read_excel(uploaded_file, header=1)

        df.columns = [str(c).strip().title() for c in df.columns]
        col_map = {}
        for c in df.columns:
            cl = c.lower()
            if 'course' in cl: col_map[c] = 'course_code'
            elif 'subject' in cl: col_map[c] = 'subject'
            elif 'theory' in cl: col_map[c] = 'theory_lab'
            elif 'credit' in cl: col_map[c] = 'credit_hours'
            elif 'clo' in cl and 'statement' not in cl: col_map[c] = 'clo_id'
            elif 'statement' in cl: col_map[c] = 'statement'
            elif 'plo' in cl: col_map[c] = 'plo'
            elif 'bloom' in cl: col_map[c] = 'bloom'
            elif 'knowledge' in cl: col_map[c] = 'kp'
            elif 'sgd' in cl: col_map[c] = 'sgds'
            elif 'complexity' in cl or 'ec' in cl: col_map[c] = 'ec'
            elif 'note' in cl: col_map[c] = 'notes'
        df = df.rename(columns=col_map)
        if 'subject' in df.columns: df['subject'] = df['subject'].ffill()
        if 'course_code' in df.columns and 'subject' in df.columns:
            df['course_code'] = df.groupby('subject')['course_code'].ffill().fillna("MISSING")
        if 'clo_id' in df.columns:
            df = df.dropna(subset=['clo_id'])
            df = df[df['clo_id'].astype(str).str.contains("CLO", case=False, na=False)]
        fill_cols = ['kp', 'sgds', 'ec', 'theory_lab', 'credit_hours', 'bloom', 'notes']
        for col in fill_cols:
            if col in df.columns:
                df[col] = df.groupby('course_code')[col].ffill()
        df = df.fillna("")
        df = df.drop_duplicates(subset=['course_code', 'clo_id', 'statement'])
        return df
    except Exception as e:
        st.error(f"Error Parsing File: {e}")
        return None

# --- 6. APP UI ---
init_db()

st.sidebar.title("🎓 OBE System")
if DB_TYPE == "POSTGRES":
    st.sidebar.success("☁️ Cloud DB Active")
else:
    st.sidebar.warning("💻 Local DB Active")

role = st.sidebar.radio("Navigation", ["Public View", "Faculty Editor", "Admin Dashboard"])

# =======================================================
# VIEW 1: PUBLIC (Sorted)
# =======================================================
if role == "Public View":
    st.title("📘 Approved Curriculum")
    if st.button("🔄 Refresh"): st.rerun()
    
    # SORTED QUERY
    df = run_query("SELECT * FROM inventory ORDER BY course_code, clo_id", fetch=True)
    
    if df is None or df.empty:
        st.warning("⚠️ Database empty.")
    else:
        df['label'] = df['course_code'] + " : " + df['subject']
        search_list = ["All Courses"] + sorted(df['label'].unique().tolist())
        sel_label = st.selectbox("Search Course:", search_list)
        
        if sel_label != "All Courses":
            df_show = df[df['label'] == sel_label].copy()
            # Strict CLO Sort in Pandas to be double sure
            df_show = df_show.sort_values('clo_id')
            n = len(df_show)
            if 3 <= n <= 6: st.success(f"✅ Compliant ({n} CLOs)")
            else: st.error(f"❌ Non-Compliant ({n} CLOs). Target: 3-6.")
        else:
            df_show = df.copy()

        cols = {'course_code': 'Course', 'subject': 'Subject', 'theory_lab': 'Type', 'credit_hours': 'Cr.Hr', 
                'clo_id': 'CLO ID', 'statement': 'Statement', 'plo': 'PLO', 'bloom': 'Bloom', 'kp': 'KP', 'sgds': 'SGDs', 'ec': 'EC'}
        final_df = df_show[[c for c in cols.keys() if c in df_show.columns]].rename(columns=cols)
        st.dataframe(final_df, hide_index=True, use_container_width=True)

# =======================================================
# VIEW 2: FACULTY (Sorted)
# =======================================================
elif role == "Faculty Editor":
    st.title("🛠️ Faculty Editor")
    df = run_query("SELECT * FROM inventory ORDER BY course_code, clo_id", fetch=True)
    if df is None or df.empty:
        st.info("No data.")
    else:
        df['label'] = df['course_code'] + " : " + df['subject']
        unique_labels = sorted(df['label'].unique().tolist())
        lbl = st.selectbox("Select Course:", unique_labels)
        
        subset = df[df['label'] == lbl].sort_values('clo_id')
        st.markdown(f"### CLOs for {lbl}")
        st.dataframe(subset[['clo_id', 'statement', 'plo', 'bloom', 'kp', 'sgds', 'ec']], hide_index=True, use_container_width=True)
        st.divider()
        
        tab_edit, tab_del = st.tabs(["✏️ Edit CLO", "🗑️ Delete CLO"])
        with tab_edit:
            clo_to_edit = st.selectbox("Select CLO:", subset['clo_id'].unique())
            row = subset[subset['clo_id'] == clo_to_edit].iloc[0]
            with st.form("edit"):
                new_stmt = st.text_area("Statement", row['statement'], height=100)
                c1, c2, c3 = st.columns(3)
                with c1: 
                    try: i = PLOS.index(row['plo'])
                    except: i=0
                    new_plo = st.selectbox("PLO", PLOS, index=i)
                with c2:
                    try: i = BLOOMS.index(row['bloom'])
                    except: i=0
                    new_bloom = st.selectbox("Bloom", BLOOMS, index=i)
                with c3: new_kp = st.selectbox("KP", [""]+WKS, index=0 if not row['kp'] in WKS else WKS.index(row['kp'])+1)
                c4, c5 = st.columns(2)
                with c4: new_sgd = st.selectbox("SGD", [""]+SDGS, index=0 if not row['sgds'] in SDGS else SDGS.index(row['sgds'])+1)
                with c5: new_ec = st.selectbox("EC", [""]+ECS, index=0 if not row['ec'] in ECS else ECS.index(row['ec'])+1)
                new_note = st.text_area("Internal Notes", row['notes'])
                
                if st.form_submit_button("Submit Request"):
                    run_query("""INSERT INTO drafts (inv_id, course_code, subject, clo_id, new_statement, new_plo, new_bloom, new_kp, new_sgds, new_ec, new_notes, request_type, requester) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", 
                              (int(row['id']), row['course_code'], row['subject'], row['clo_id'], new_stmt, new_plo, new_bloom, new_kp, new_sgd, new_ec, new_note, 'UPDATE', "Faculty"))
                    st.success("Sent to Admin.")

        with tab_del:
            clo_del = st.selectbox("Delete which CLO?", subset['clo_id'].unique(), key="del")
            if st.button("Request Deletion"):
                r = subset[subset['clo_id'] == clo_del].iloc[0]
                run_query("INSERT INTO drafts (inv_id, course_code, subject, clo_id, request_type, requester) VALUES (?,?,?,?,?,?)", 
                          (int(r['id']), r['course_code'], r['subject'], r['clo_id'], 'DELETE', "Faculty"))
                st.error("Deletion Request Sent.")

# =======================================================
# VIEW 3: ADMIN (Sorted)
# =======================================================
elif role == "Admin Dashboard":
    st.title("🔐 Admin Dashboard")
    if st.sidebar.text_input("Password", type="password") == ADMIN_PASSWORD:
        t1, t2, t3, t4 = st.tabs(["⚡ Live Editor", "➕ Create Course", "📥 Upload", "⚖️ Approvals"])
        
        with t1:
            st.info("Hover over row numbers to delete.")
            # SORTED QUERY
            df_live = run_query("SELECT * FROM inventory ORDER BY course_code, clo_id", fetch=True)
            if df_live is None: df_live = pd.DataFrame()
            edited_df = st.data_editor(df_live, num_rows="dynamic", use_container_width=True, hide_index=True, key="editor")
            if st.button("💾 SAVE CHANGES"):
                run_query("DELETE FROM inventory")
                for _, row in edited_df.iterrows():
                    run_query("""INSERT INTO inventory (course_code, subject, theory_lab, credit_hours, clo_id, statement, plo, bloom, kp, sgds, ec, notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (
                        row['course_code'], row['subject'], row['theory_lab'], row['credit_hours'],
                        row['clo_id'], row['statement'], row['plo'], row['bloom'],
                        row['kp'], row['sgds'], row['ec'], row['notes']))
                st.success("Updated!")
                time.sleep(0.5)
                st.rerun()

        with t2:
            st.subheader("Add New Course")
            c1, c2, c3, c4 = st.columns(4)
            with c1: new_code = st.text_input("Course Code (e.g. ME-205)")
            with c2: new_sub = st.text_input("Subject Title")
            with c3: new_type = st.selectbox("Type", ["Theory", "Lab"])
            with c4: new_cr = st.text_input("Credits", "3")
            st.write("**Define CLOs:**")
            empty_data = pd.DataFrame([{"CLO ID": f"CLO-{i}", "Statement": "", "PLO": "PLO-1", "Bloom": "C1", "KP": "", "SGD": "", "EC": ""} for i in range(1,5)])
            new_clos_df = st.data_editor(empty_data, num_rows="dynamic", use_container_width=True, column_config={"PLO": st.column_config.SelectboxColumn("PLO", options=PLOS), "Bloom": st.column_config.SelectboxColumn("Bloom", options=BLOOMS), "KP": st.column_config.SelectboxColumn("KP", options=[""]+WKS)})
            if st.button("🚀 CREATE COURSE"):
                if new_code and new_sub:
                    count = 0
                    for _, row in new_clos_df.iterrows():
                        if row["Statement"] and str(row["Statement"]).strip():
                            run_query("""INSERT INTO inventory (course_code, subject, theory_lab, credit_hours, clo_id, statement, plo, bloom, kp, sgds, ec, notes) 
                                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (new_code, new_sub, new_type, new_cr, row["CLO ID"], row["Statement"], row["PLO"], row["Bloom"], row["KP"], row["SGD"], row["EC"], ""))
                            count += 1
                    if count > 0:
                        st.success(f"✅ Created {new_code} with {count} CLOs!")
                        time.sleep(1)
                        st.rerun()
                    else: st.error("Fill at least one CLO.")
                else: st.error("Code and Subject required.")

        with t3:
            f = st.file_uploader("Upload Inventory", type=['xlsx', 'csv'])
            if f and st.button("Process & Replace"):
                df_clean = smart_parse_file(f)
                if df_clean is not None:
                    run_query("DELETE FROM inventory")
                    for _, r in df_clean.iterrows():
                        run_query("INSERT INTO inventory (course_code, subject, theory_lab, credit_hours, clo_id, statement, plo, bloom, kp, sgds, ec, notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
                            r.get('course_code'), r.get('subject'), r.get('theory_lab',''), r.get('credit_hours',''),
                            r.get('clo_id'), r.get('statement'), r.get('plo'), r.get('bloom'), r.get('kp',''), 
                            r.get('sgds',''), r.get('ec',''), r.get('notes','')))
                    st.success("Database Reset!")

        with t4:
            drafts = run_query("SELECT * FROM drafts", fetch=True)
            if drafts is None or drafts.empty:
                st.info("No pending tasks.")
            else:
                st.write(f"Pending Requests: {len(drafts)}")
                for idx, row in drafts.iterrows():
                    if row['request_type'] == 'DELETE':
                        with st.expander(f"🗑️ DELETE REQUEST: {row['course_code']} - {row['clo_id']}"):
                            st.error(f"Request to DELETE {row['clo_id']}")
                            c1, c2 = st.columns(2)
                            if c1.button("Confirm", key=f"d_y_{row['id']}"):
                                run_query("DELETE FROM inventory WHERE id=?", (row['inv_id'],))
                                run_query("DELETE FROM drafts WHERE id=?", (row['id'],))
                                st.rerun()
                            if c2.button("Reject", key=f"d_n_{row['id']}"):
                                run_query("DELETE FROM drafts WHERE id=?", (row['id'],))
                                st.rerun()
                    elif row['request_type'] == 'UPDATE':
                        with st.expander(f"✏️ UPDATE REQUEST: {row['course_code']} - {row['clo_id']}"):
                            st.write(f"**New Statement:** {row['new_statement']}")
                            c1, c2 = st.columns(2)
                            if c1.button("Approve", key=f"u_y_{row['id']}"):
                                run_query("""UPDATE inventory SET statement=?, plo=?, bloom=?, kp=?, sgds=?, ec=?, notes=? WHERE id=?""", (
                                    row['new_statement'], row['new_plo'], row['new_bloom'], row['new_kp'], row['new_sgds'], row['new_ec'], row['new_notes'], row['inv_id']))
                                run_query("DELETE FROM drafts WHERE id=?", (row['id'],))
                                st.rerun()
                            if c2.button("Reject", key=f"u_n_{row['id']}"):
                                run_query("DELETE FROM drafts WHERE id=?", (row['id'],))
                                st.rerun()