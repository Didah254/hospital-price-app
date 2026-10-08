# Hospital Procurement - Fair Price System
import streamlit as st
import joblib
import pandas as pd
import numpy as np
from datetime import datetime
import os
import time
import uuid
from io import BytesIO
from collections import Counter
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

st.set_page_config(page_title="Hospital Fair Price System", page_icon="🏥", layout="wide")
st.title("Hospital Procurement – Fair Price System")

# ====================== GOOGLE DRIVE HELPERS (COMPLETELY SILENT) ======================
def get_drive_service():
    try:
        creds_info = st.secrets["gcp_service_account"]
        credentials = service_account.Credentials.from_service_account_info(
            creds_info,
            scopes=["https://www.googleapis.com/auth/drive"]
        )
        return build("drive", "v3", credentials=credentials)
    except Exception:
        return None

def upload_to_drive(local_path, drive_filename):
    try:
        service = get_drive_service()
        if service is None:
            return False
        folder_id = st.secrets["folder_id"]
        query = f"name='{drive_filename}' and '{folder_id}' in parents and trashed=false"
        results = service.files().list(q=query, fields="files(id)").execute()
        files = results.get("files", [])
        media = MediaFileUpload(local_path, resumable=True)
        if files:
            file_id = files[0]["id"]
            service.files().update(fileId=file_id, media_body=media).execute()
        else:
            file_metadata = {
                "name": drive_filename,
                "parents": [folder_id]
            }
            service.files().create(
                body=file_metadata,
                media_body=media,
                fields="id"
            ).execute()
        return True
    except Exception:
        return False

def download_from_drive(drive_filename, local_path):
    try:
        service = get_drive_service()
        if service is None:
            return False
        folder_id = st.secrets["folder_id"]
        query = f"name='{drive_filename}' and '{folder_id}' in parents and trashed=false"
        results = service.files().list(q=query, fields="files(id, name)").execute()
        files = results.get("files", [])
        if not files:
            return False
        file_id = files[0]["id"]
        request = service.files().get_media(fileId=file_id)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "wb") as f:
            downloader = MediaIoBaseDownload(f, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
        return True
    except Exception:
        return False

def recover_files_from_drive():
    files_to_recover = [
        ("live_purchase_history.joblib", "price_models/live_purchase_history.joblib"),
        ("Live_Purchase_History.xlsx", "price_models/Live_Purchase_History.xlsx"),
        ("promoted_products.joblib", "price_models/promoted_products.joblib"),
    ]
    for drive_name, local_path in files_to_recover:
        if not os.path.exists(local_path):
            download_from_drive(drive_name, local_path)

# ====================== LOAD MODELS ======================
@st.cache_resource
def load_resources():
    base = "price_models"
    return {
        "model_low": joblib.load(f"{base}/model_low.joblib"),
        "model_med": joblib.load(f"{base}/model_med.joblib"),
        "model_high": joblib.load(f"{base}/model_high.joblib"),
        "le_desc_low": joblib.load(f"{base}/le_desc_low.joblib"),
        "le_sup_low": joblib.load(f"{base}/le_sup_low.joblib"),
        "le_cat_low": joblib.load(f"{base}/le_cat_low.joblib"),
        "le_desc_med": joblib.load(f"{base}/le_desc_med.joblib"),
        "le_sup_med": joblib.load(f"{base}/le_sup_med.joblib"),
        "le_cat_med": joblib.load(f"{base}/le_cat_med.joblib"),
        "le_desc_high": joblib.load(f"{base}/le_desc_high.joblib"),
        "le_sup_high": joblib.load(f"{base}/le_sup_high.joblib"),
        "le_cat_high": joblib.load(f"{base}/le_cat_high.joblib"),
        "low_products": joblib.load(f"{base}/low_products.joblib"),
        "medium_products": joblib.load(f"{base}/medium_products.joblib"),
        "high_products": joblib.load(f"{base}/high_products.joblib"),
        "all_known_products": joblib.load(f"{base}/all_known_products.joblib"),
        "product_supplier_history": joblib.load(f"{base}/product_supplier_history.joblib"),
    }

recover_files_from_drive()

try:
    res = load_resources()
except Exception as e:
    st.error(f"Could not load files from the price_models folder.\n\n{e}")
    st.stop()

# ========== Promoted products ==========
PROMOTED_PATH = "price_models/promoted_products.joblib"
LOCK_FILE = "price_models/history.lock"

def load_promoted_products():
    if os.path.exists(PROMOTED_PATH):
        return joblib.load(PROMOTED_PATH)
    return []

def save_promoted_products(promoted_list):
    joblib.dump(promoted_list, PROMOTED_PATH)
    upload_to_drive(PROMOTED_PATH, "promoted_products.joblib")

def get_all_known_products():
    promoted = load_promoted_products()
    return sorted(list(set(res["all_known_products"] + promoted)))

def check_and_promote_product(description):
    description = str(description).upper().strip()
    prices, _, _ = get_product_price_history(description)
    total_purchases = len(prices)
    if total_purchases >= 3:
        promoted = load_promoted_products()
        if description not in promoted and description not in res["all_known_products"]:
            promoted.append(description)
            save_promoted_products(promoted)
            return True
    return False

# ======================================================================
def load_live_history():
    path = "price_models/live_purchase_history.joblib"
    if os.path.exists(path):
        return joblib.load(path)
    return []

def save_live_history(history, max_retries=8):
    lock_id = str(uuid.uuid4())
    acquired = False
    for attempt in range(max_retries):
        try:
            if not os.path.exists(LOCK_FILE):
                with open(LOCK_FILE, "w") as f:
                    f.write(lock_id)
                time.sleep(0.05)
                with open(LOCK_FILE, "r") as f:
                    if f.read().strip() == lock_id:
                        acquired = True
                        break
            else:
                time.sleep(0.4 + attempt * 0.15)
        except Exception:
            time.sleep(0.3)
    if not acquired:
        return False
    try:
        joblib.dump(history, "price_models/live_purchase_history.joblib")
        pd.DataFrame(history).to_excel("price_models/Live_Purchase_History.xlsx", index=False)
        upload_to_drive("price_models/live_purchase_history.joblib", "live_purchase_history.joblib")
        upload_to_drive("price_models/Live_Purchase_History.xlsx", "Live_Purchase_History.xlsx")
        return True
    finally:
        try:
            if os.path.exists(LOCK_FILE):
                with open(LOCK_FILE, "r") as f:
                    if f.read().strip() == lock_id:
                        os.remove(LOCK_FILE)
        except:
            pass

def get_all_suppliers():
    suppliers = set()
    for prod, data in res["product_supplier_history"].items():
        for row in data.get("summary", []):
            suppliers.add(str(row.get("Supplier", "")).upper().strip())
    live = load_live_history()
    for rec in live:
        suppliers.add(str(rec.get("Supplier", "")).upper().strip())
    suppliers.discard("")
    return sorted(list(suppliers))

def get_product_price_history(description):
    description = str(description).upper().strip()
    prices = []
    suppliers = []
    details = []
    if description in res["product_supplier_history"]:
        for d in res["product_supplier_history"][description].get("details", []):
            try:
                price = float(d.get("Price", 0))
                qty = float(d.get("Quantity", 0) or 0)
                sup = str(d.get("Supplier", "")).upper().strip()
                prices.append(price)
                suppliers.append(sup)
                details.append({
                    "Supplier": sup,
                    "Price": price,
                    "Quantity": qty,
                    "Date": str(d.get("Date", ""))
                })
            except:
                pass
    live = load_live_history()
    for rec in live:
        if str(rec.get("Description", "")).upper().strip() == description:
            try:
                price = float(rec.get("Price", 0))
                qty = float(rec.get("Quantity", 0) or 0)
                sup = str(rec.get("Supplier", "")).upper().strip()
                prices.append(price)
                suppliers.append(sup)
                details.append({
                    "Supplier": sup,
                    "Price": price,
                    "Quantity": qty,
                    "Date": str(rec.get("Date", ""))
                })
            except:
                pass
    return prices, suppliers, details

def get_product_category(description):
    """Return the most common category for a product from original + live data.
       Falls back to careful keyword detection if no category is found."""
    description = str(description).upper().strip()
    categories = []

    # 1. Highest priority: Original data
    if description in res["product_supplier_history"]:
        for d in res["product_supplier_history"][description].get("details", []):
            cat = str(d.get("Category", "")).upper().strip()
            if cat and cat not in ["", "NAN", "NONE", "NULL"]:
                categories.append(cat)

    # 2. Live history
    live = load_live_history()
    for rec in live:
        if str(rec.get("Description", "")).upper().strip() == description:
            cat = str(rec.get("Category", "")).upper().strip()
            if cat and cat not in ["", "NAN", "NONE", "NULL"]:
                categories.append(cat)

    if categories:
        return Counter(categories).most_common(1)[0][0]

    # 3. Careful keyword fallback
    name = description

    # CONSUMABLE
    consumable_keywords = [
        "TRAY", "ENVELOP", "ENVELOPE", "GLOVE", "GLOVES", "MASK", "MASKS",
        "SYRINGE", "NEEDLE", "CATHETER", "TUBE", "BAG", "BANDAGE", "GAUZE",
        "COTTON", "SWAB", "DRESSING", "PLASTER", "TAPE", "SHEET", "COVER",
        "APRON", "GOWN", "CAP", "SHOE", "BOOT", "SUTURE", "BLADE", "SCALPEL",
        "FORCEPS", "CLAMP", "SCISSOR", "CONTAINER", "BOTTLE", "VIAL", "AMPOULE",
        "PAPER", "PHOTOCOPY", "A4", "TONER", "INK", "CARTRIDGE", "STAPLER",
        "STAPLE", "CLIP", "FOLDER", "FILE", "PEN", "PENCIL", "MARKER",
        "TISSUE", "TOWEL", "SOAP", "DETERGENT", "DISINFECTANT", "SANITIZER"
    ]
    for kw in consumable_keywords:
        if kw in name:
            return "CONSUMABLE"

    # LAB
    lab_keywords = [
        "REAGENT", "TEST", "KIT", "STRIP", "SLIDE", "CULTURE", "AGAR",
        "PIPETTE", "SAMPLE", "SPECIMEN", "ANALYZER", "CASSETTE", "LAB"
    ]
    for kw in lab_keywords:
        if kw in name:
            return "LAB"

    # THEATRE
    theatre_keywords = [
        "SUTURE", "BLADE", "SCALPEL", "FORCEPS", "CLAMP", "RETRACTOR",
        "SCISSOR", "NEEDLE HOLDER", "SURGICAL", "OPERATING", "THEATRE"
    ]
    for kw in theatre_keywords:
        if kw in name:
            return "THEATRE"

    # OTHER (non-medical / administrative)
    other_keywords = [
        "TRANSPORT", "CHARGE", "CHARGES", "FREIGHT", "DELIVERY", "SHIPPING",
        "LABOUR", "LABOR", "SERVICE", "INSTALLATION", "MAINTENANCE",
        "REPAIR", "CONSULTANCY", "FEE", "ALLOWANCE", "PER DIEM",
        "VAT", "TAX", "TAXES", "DUTY", "LEVY", "CESS", "BANK", "COMMISSION"
    ]
    for kw in other_keywords:
        if kw in name:
            return "OTHER"

    return "DRUG"

def predict_fair_price(description, quantity, supplier, month, proposed_price, category="DRUG"):
    description = str(description).upper().strip()
    supplier = str(supplier).upper().strip()
    hist_prices, hist_suppliers, hist_details = get_product_price_history(description)
    hist_median = np.median(hist_prices) if hist_prices else None
    hist_mean = np.mean(hist_prices) if hist_prices else None
    hist_min = min(hist_prices) if hist_prices else None
    hist_max = max(hist_prices) if hist_prices else None
    is_new_supplier = supplier not in [s.upper() for s in hist_suppliers]
    unique_suppliers = list(set([s for s in hist_suppliers if s]))
    times_purchased = len(hist_prices)
    suppliers_count = len(unique_suppliers)
    supplier_breakdown = []
    if hist_details:
        df_hist = pd.DataFrame(hist_details)
        breakdown = (
            df_hist.groupby("Supplier")
            .agg(
                Times_Supplied=("Price", "count"),
                Average_Price=("Price", "mean"),
                Min_Price=("Price", "min"),
                Max_Price=("Price", "max"),
                Total_Quantity=("Quantity", "sum")
            )
            .round(2)
            .reset_index()
            .sort_values("Times_Supplied", ascending=False)
        )
        supplier_breakdown = breakdown.to_dict("records")
    if description in res["low_products"]:
        model = res["model_low"]
        le_desc, le_sup, le_cat = res["le_desc_low"], res["le_sup_low"], res["le_cat_low"]
        group = "Low-value"
    elif description in res["medium_products"]:
        model = res["model_med"]
        le_desc, le_sup, le_cat = res["le_desc_med"], res["le_sup_med"], res["le_cat_med"]
        group = "Medium-value"
    elif description in res["high_products"]:
        model = res["model_high"]
        le_desc, le_sup, le_cat = res["le_desc_high"], res["le_sup_high"], res["le_cat_high"]
        group = "High-value"
    else:
        if len(hist_prices) < 3:
            return {
                "Message": f"Only {len(hist_prices)} purchase(s) recorded so far. At least 3 are needed for a reliable estimate.",
                "Recorded prices": hist_prices,
                "Is New Supplier": is_new_supplier
            }
        expected = hist_median
        variance = ((proposed_price - expected) / expected) * 100 if expected else 0
        status = "HIGH – Review required" if variance > 20 else ("MEDIUM – Ask for justification" if variance > 10 else "ACCEPTABLE")
        return {
            "Product Group": "History-based",
            "Expected fair price (KES)": round(float(expected), 2),
            "Proposed price (KES)": proposed_price,
            "Difference %": round(float(variance), 1),
            "Recommendation": status,
            "Historical Median": round(float(hist_median), 2) if hist_median else None,
            "Historical Average": round(float(hist_mean), 2) if hist_mean else None,
            "Historical Min": round(float(hist_min), 2) if hist_min else None,
            "Historical Max": round(float(hist_max), 2) if hist_max else None,
            "Is New Supplier": is_new_supplier,
            "Previous Suppliers": unique_suppliers,
            "Times Purchased": times_purchased,
            "Suppliers Count": suppliers_count,
            "Supplier Breakdown": supplier_breakdown
        }
    try:
        desc_enc = le_desc.transform([description])[0]
    except:
        if hist_median is not None:
            expected = hist_median
            variance = ((proposed_price - expected) / expected) * 100
            status = "HIGH – Review required" if variance > 20 else ("MEDIUM – Ask for justification" if variance > 10 else "ACCEPTABLE")
            return {
                "Product Group": group,
                "Expected fair price (KES)": round(float(expected), 2),
                "Proposed price (KES)": proposed_price,
                "Difference %": round(float(variance), 1),
                "Recommendation": status,
                "Historical Median": round(float(hist_median), 2),
                "Historical Average": round(float(hist_mean), 2),
                "Historical Min": round(float(hist_min), 2),
                "Historical Max": round(float(hist_max), 2),
                "Is New Supplier": is_new_supplier,
                "Previous Suppliers": unique_suppliers,
                "Times Purchased": times_purchased,
                "Suppliers Count": suppliers_count,
                "Supplier Breakdown": supplier_breakdown
            }
        return predict_from_history(description, proposed_price)
    try:
        sup_enc = le_sup.transform([supplier])[0]
    except:
        sup_enc = 0
    try:
        cat_enc = le_cat.transform([category.upper()])[0]
    except:
        cat_enc = 0
    X = np.array([[desc_enc, quantity, month, sup_enc, cat_enc]])
    expected = model.predict(X)[0]
    variance = ((proposed_price - expected) / expected) * 100
    if variance > 20:
        status = "HIGH – Review required before approval"
    elif variance > 10:
        status = "MEDIUM – Ask for justification"
    else:
        status = "ACCEPTABLE"
    result = {
        "Product Group": group,
        "Expected fair price (KES)": round(float(expected), 2),
        "Proposed price (KES)": proposed_price,
        "Difference %": round(float(variance), 1),
        "Recommendation": status,
        "Is New Supplier": is_new_supplier
    }
    if hist_prices:
        result["Historical Median"] = round(float(hist_median), 2)
        result["Historical Average"] = round(float(hist_mean), 2)
        result["Historical Min"] = round(float(hist_min), 2)
        result["Historical Max"] = round(float(hist_max), 2)
        result["Previous Suppliers"] = unique_suppliers
        result["Times Purchased"] = times_purchased
        result["Suppliers Count"] = suppliers_count
        result["Supplier Breakdown"] = supplier_breakdown
        if is_new_supplier and hist_median and proposed_price > hist_median * 1.15:
            result["Recommendation"] = "HIGH – New supplier price is much higher than previous suppliers"
        elif is_new_supplier and hist_median and proposed_price > hist_median * 1.08:
            result["Recommendation"] = "MEDIUM – New supplier price is higher than previous average"
    return result

def predict_from_history(description, proposed_price):
    description = str(description).upper().strip()
    history = load_live_history()
    df = pd.DataFrame(history)
    product_df = df[df["Description"] == description]
    if len(product_df) < 3:
        return {
            "Message": f"Only {len(product_df)} purchase(s) recorded so far. At least 3 are needed for a reliable estimate.",
            "Recorded prices": product_df["Price"].tolist() if len(product_df) > 0 else []
        }
    median_price = product_df["Price"].median()
    variance = ((proposed_price - median_price) / median_price) * 100
    if variance > 20:
        status = "HIGH – Review required"
    elif variance > 10:
        status = "MEDIUM – Ask for justification"
    else:
        status = "ACCEPTABLE"
    return {
        "Times recorded": len(product_df),
        "Suppliers used": int(product_df["Supplier"].nunique()),
        "Median price (KES)": round(float(median_price), 2),
        "Average price (KES)": round(float(product_df["Price"].mean()), 2),
        "Proposed price (KES)": proposed_price,
        "Difference %": round(float(variance), 1),
        "Recommendation": status,
        "Times Purchased": len(product_df),
        "Suppliers Count": int(product_df["Supplier"].nunique())
    }

def to_excel_download(df, filename):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Report")
    return output.getvalue()

def show_clean_result(result):
    if "Message" in result:
        st.info(result["Message"])
        if result.get("Recorded prices"):
            st.write("Recorded prices so far: " + ", ".join([str(p) for p in result["Recorded prices"]]))
        return
    st.markdown("### Result")
    st.write(f"**Product Group:** {result.get('Product Group', 'N/A')}")
    if result.get("Times Purchased") is not None and result.get("Suppliers Count") is not None:
        st.info(f"**Based on {result['Times Purchased']} purchases from {result['Suppliers Count']} different suppliers**")
        if result.get("Supplier Breakdown"):
            st.markdown("#### Supplier Breakdown")
            breakdown_df = pd.DataFrame(result["Supplier Breakdown"])
            breakdown_df = breakdown_df.rename(columns={
                "Supplier": "Supplier",
                "Times_Supplied": "Times Supplied",
                "Average_Price": "Avg Price (KES)",
                "Min_Price": "Min Price (KES)",
                "Max_Price": "Max Price (KES)",
                "Total_Quantity": "Total Qty"
            })
            st.dataframe(breakdown_df, use_container_width=True)
    st.write(f"**Expected Fair Price:** KES {result.get('Expected fair price (KES)', result.get('Median price (KES)', 'N/A'))}")
    st.write(f"**Proposed Price:** KES {result.get('Proposed price (KES)', 'N/A')}")
    st.write(f"**Difference:** {result.get('Difference %', 'N/A')}%")
    if result.get("Is New Supplier"):
        st.warning("This is a **new supplier** for this product.")
    if result.get("Historical Median"):
        st.markdown("#### Comparison with previous suppliers")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Historical Median", f"KES {result['Historical Median']}")
        col2.metric("Historical Average", f"KES {result['Historical Average']}")
        col3.metric("Lowest Previous", f"KES {result['Historical Min']}")
        col4.metric("Highest Previous", f"KES {result['Historical Max']}")
    recommendation = result.get("Recommendation", "")
    if "HIGH" in recommendation:
        st.error(f"**Recommendation:** {recommendation}")
    elif "MEDIUM" in recommendation:
        st.warning(f"**Recommendation:** {recommendation}")
    else:
        st.success(f"**Recommendation:** {recommendation}")

# ====================== BACKUP & RESTORE SECTION ======================
st.markdown("---")
with st.expander("Backup & Restore Purchase History", expanded=False):
    st.caption("Download a backup before updating the app. After updating, upload the backup to restore all records.")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### Download Backup")
        history = load_live_history()
        promoted = load_promoted_products()

        if st.button("Download Full Backup (Excel)", type="primary", use_container_width=True):
            if not history and not promoted:
                st.warning("No data to download.")
            else:
                output = BytesIO()
                with pd.ExcelWriter(output, engine="openpyxl") as writer:
                    if history:
                        pd.DataFrame(history).to_excel(writer, index=False, sheet_name="Live_Purchases")
                    else:
                        pd.DataFrame(columns=[
                            "Date", "Description", "Supplier", "Category",
                            "Quantity", "Price", "Amount", "Notes", "Registered_On"
                        ]).to_excel(writer, index=False, sheet_name="Live_Purchases")

                    pd.DataFrame({"Promoted_Product": promoted}).to_excel(
                        writer, index=False, sheet_name="Promoted_Products"
                    )

                st.download_button(
                    label="Click here to download the Excel backup",
                    data=output.getvalue(),
                    file_name=f"Hospital_Backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
                st.success(f"Backup ready — {len(history)} purchases + {len(promoted)} promoted products")

    with col2:
        st.markdown("#### Upload & Restore")
        uploaded_file = st.file_uploader(
            "Upload previous Excel backup",
            type=["xlsx"],
            help="Upload a previously downloaded backup to restore all records"
        )

        if uploaded_file is not None:
            try:
                live_df = pd.read_excel(uploaded_file, sheet_name="Live_Purchases")
                promoted_df = pd.read_excel(uploaded_file, sheet_name="Promoted_Products")

                restored_history = live_df.to_dict("records") if not live_df.empty else []
                restored_promoted = promoted_df["Promoted_Product"].dropna().tolist() if "Promoted_Product" in promoted_df.columns else []

                st.warning(
                    f"This will restore:\n"
                    f"- **{len(restored_history)}** purchase records\n"
                    f"- **{len(restored_promoted)}** promoted products\n\n"
                    f"Current data will be replaced."
                )

                if st.button("Confirm Restore", type="primary", use_container_width=True):
                    success1 = save_live_history(restored_history)
                    save_promoted_products(restored_promoted)

                    if success1:
                        st.success("Restore completed successfully!")
                        st.balloons()
                        time.sleep(1.5)
                        st.rerun()
                    else:
                        st.error("Could not save. Please try again in a few seconds.")

            except Exception as e:
                st.error(f"Error reading the backup file: {e}")

    st.caption(f"Current live records: **{len(load_live_history())}** | Promoted products: **{len(load_promoted_products())}**")

# ====================== MENU ======================
st.markdown("---")
menu = st.selectbox(
    "Select Action",
    [
        "Check Fair Price",
        "Register Purchase",
        "View Product History",
        "Search Products",
        "New Products & Reports",
        "Most Frequent Products"
    ],
    index=0
)
st.markdown("---")

# PAGE 1: Check Fair Price
if menu == "Check Fair Price":
    st.subheader("Check Fair Price")
    all_known = get_all_known_products()
    selected_product = st.selectbox(
        "Select Product",
        options=all_known,
        index=None,
        placeholder="Type to search or select a product..."
    )
    new_product = st.text_input("Or type a new product name (leave empty if you selected above)")
    product_to_use = new_product.strip().upper() if new_product.strip() else selected_product
    if product_to_use:
        st.markdown(f"**Selected Product:** {product_to_use}")

        suggested_category = get_product_category(product_to_use)
        category_options = ["DRUG", "CONSUMABLE", "LAB", "THEATRE", "OTHER"]
        try:
            default_index = category_options.index(suggested_category)
        except:
            default_index = 0

        product_category = st.selectbox(
            "Category (auto-detected – you can change it)",
            options=category_options,
            index=default_index,
            help=f"Auto-detected as **{suggested_category}**. Change it if needed."
        )

        if product_to_use in res["product_supplier_history"]:
            summary_df = pd.DataFrame(res["product_supplier_history"][product_to_use]["summary"])
            st.write("**Suppliers who previously supplied this product**")
            st.dataframe(summary_df, use_container_width=True)
        live = load_live_history()
        live_df = pd.DataFrame(live) if live else pd.DataFrame()
        if len(live_df) > 0:
            live_for_prod = live_df[live_df["Description"] == product_to_use]
            if len(live_for_prod) > 0:
                st.write("**Recent live purchases for this product**")
                st.dataframe(live_for_prod[["Date", "Supplier", "Quantity", "Price"]].sort_values("Date", ascending=False), use_container_width=True)
        all_sups = get_all_suppliers()
        supplier_options = all_sups + ["-- Add New Supplier --"]
        selected_supplier = st.selectbox("Select Supplier", options=supplier_options, index=None, placeholder="Type to search supplier...")
        if selected_supplier == "-- Add New Supplier --":
            selected_supplier = st.text_input("Enter new supplier name")
        col1, col2, col3 = st.columns(3)
        with col1:
            quantity = st.number_input("Quantity", min_value=1.0, value=1.0)
        with col2:
            proposed_price = st.number_input("Proposed Price (KES)", min_value=0.0, value=0.0)
        with col3:
            month = st.number_input("Month (1-12)", min_value=1, max_value=12, value=datetime.now().month)
        if st.button("Check if Price is Fair", type="primary"):
            if not selected_supplier or proposed_price <= 0:
                st.warning("Please enter Supplier and Proposed Price.")
            else:
                result = predict_fair_price(
                    product_to_use, quantity, selected_supplier, month, proposed_price, category=product_category
                )
                show_clean_result(result)
                report_df = pd.DataFrame([result])
                excel_data = to_excel_download(report_df, "fair_price_report.xlsx")
                st.download_button(
                    label="Download this result (Excel)",
                    data=excel_data,
                    file_name=f"Fair_Price_{product_to_use[:30]}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

# PAGE 2: Register Purchase
elif menu == "Register Purchase":
    st.subheader("Register Purchase")
    st.caption("Record every purchase. The tracker shows each product on one row with prices side by side.")
    live_history = load_live_history()
    if live_history:
        live_df = pd.DataFrame(live_history)
    else:
        live_df = pd.DataFrame(columns=[
            "Date", "Description", "Supplier", "Category",
            "Quantity", "Price", "Amount", "Notes", "Registered_On"
        ])
    live_products = live_df["Description"].unique().tolist() if len(live_df) > 0 else []
    all_products = sorted(list(set(get_all_known_products() + live_products)))
    st.markdown("### Product Price Tracker")
    if len(live_df) > 0:
        tracker_rows = []
        for product in sorted(live_df["Description"].unique()):
            prod_data = live_df[live_df["Description"] == product].sort_values("Date")
            row = {"Product": product}
            for i, (_, rec) in enumerate(prod_data.iterrows(), 1):
                row[f"Date_{i}"] = rec["Date"]
                row[f"Supplier_{i}"] = rec["Supplier"]
                row[f"Qty_{i}"] = rec["Quantity"]
                row[f"Price_{i}"] = rec["Price"]
            tracker_rows.append(row)
        tracker_df = pd.DataFrame(tracker_rows)
        st.dataframe(tracker_df, use_container_width=True)
        st.download_button(
            "Download Price Tracker (Excel)",
            data=to_excel_download(tracker_df, "price_tracker.xlsx"),
            file_name="Product_Price_Tracker.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.info("No purchases recorded yet. Use the form below to add the first ones.")
    st.markdown("---")
    st.markdown("### Add New Purchase")
    selected_product = st.selectbox(
        "Search and select product",
        options=all_products,
        index=None,
        placeholder="Type product name to search...",
        key="tracker_product"
    )
    new_product = st.text_input("Or type a new product name", key="tracker_new_product")
    product_to_save = new_product.strip().upper() if new_product.strip() else (selected_product.upper().strip() if selected_product else "")
    if product_to_save:
        st.success(f"Product: **{product_to_save}**")
        already = 0
        if len(live_df) > 0:
            already = len(live_df[live_df["Description"] == product_to_save])
        st.write(f"This product has been recorded **{already}** time(s). The new price will appear as Price_{already+1}.")
        all_sups = get_all_suppliers()
        previous_records = []
        if product_to_save in res["product_supplier_history"]:
            for row in res["product_supplier_history"][product_to_save].get("details", []):
                previous_records.append({
                    "Supplier": str(row.get("Supplier", "")).upper().strip(),
                    "Price": row.get("Price", ""),
                    "Quantity": row.get("Quantity", ""),
                    "Category": row.get("Category", "DRUG"),
                    "Date": row.get("Date", "")
                })
        live = load_live_history()
        for rec in live:
            if str(rec.get("Description", "")).upper().strip() == product_to_save:
                previous_records.append({
                    "Supplier": str(rec.get("Supplier", "")).upper().strip(),
                    "Price": rec.get("Price", ""),
                    "Quantity": rec.get("Quantity", ""),
                    "Category": rec.get("Category", "DRUG"),
                    "Date": rec.get("Date", "")
                })
        previous_suppliers_for_product = sorted(list(set(
            [r["Supplier"] for r in previous_records if r["Supplier"]]
        )))
        if previous_records:
            st.markdown("#### Last times this product was supplied")
            prev_df = pd.DataFrame(previous_records)
            display_cols = [c for c in ["Date", "Supplier", "Quantity", "Price", "Category"] if c in prev_df.columns]
            prev_df = prev_df[display_cols].drop_duplicates()
            st.dataframe(prev_df, use_container_width=True)
            st.info(f"**Last suppliers for this product:** {', '.join(previous_suppliers_for_product)}")
            supplier_options = previous_suppliers_for_product + [s for s in all_sups if s not in previous_suppliers_for_product] + ["-- Add New Supplier --"]
        else:
            supplier_options = all_sups + ["-- Add New Supplier --"]
        selected_supplier = st.selectbox(
            "Select Supplier (searchable) – last suppliers appear first",
            options=supplier_options,
            index=None,
            placeholder="Type to search supplier...",
            key="tracker_supplier"
        )
        if selected_supplier == "-- Add New Supplier --":
            selected_supplier = st.text_input("Enter new supplier name", key="tracker_new_sup")
        col1, col2 = st.columns(2)
        with col1:
            qty = st.number_input("Quantity", min_value=1.0, value=1.0, step=1.0, key="tracker_qty")
            price = st.number_input("Unit Price (KES)", min_value=0.0, value=0.0, step=0.01, key="tracker_price")
        with col2:
            purchase_date = st.date_input("Date of Purchase", value=datetime.now(), key="tracker_date")

            suggested_category = get_product_category(product_to_save)
            category_options = ["DRUG", "CONSUMABLE", "LAB", "THEATRE", "OTHER"]
            try:
                default_index = category_options.index(suggested_category)
            except:
                default_index = 0

            category = st.selectbox(
                "Category (auto-detected – you can change it)",
                options=category_options,
                index=default_index,
                key="tracker_cat",
                help=f"Auto-detected as **{suggested_category}**. Change it if needed."
            )
        notes = st.text_area("Notes (optional)", key="tracker_notes")
        if st.button("Save Purchase", type="primary"):
            if not product_to_save or not selected_supplier or price <= 0:
                st.warning("Please fill Product, Supplier and a valid Price.")
            else:
                history = load_live_history()
                record = {
                    "Date": purchase_date.strftime("%Y-%m-%d"),
                    "Description": product_to_save,
                    "Supplier": selected_supplier.upper().strip(),
                    "Category": category,
                    "Quantity": float(qty),
                    "Price": float(price),
                    "Amount": float(qty) * float(price),
                    "Notes": notes,
                    "Registered_On": datetime.now().strftime("%Y-%m-%d %H:%M")
                }
                history.append(record)
                success = save_live_history(history)
                if success:
                    was_promoted = check_and_promote_product(product_to_save)
                    if was_promoted:
                        st.success(f"Saved. {product_to_save} now has {already+1} price record(s).")
                        st.balloons()
                        st.info(f"🎉 **{product_to_save}** has reached 3+ purchases and has been automatically added to the known products list!")
                    else:
                        st.success(f"Saved. {product_to_save} now has {already+1} price record(s).")
                        st.balloons()
                    st.rerun()
                else:
                    st.error("Another user is currently saving data. Please wait 3–5 seconds and try again.")
    st.markdown("---")
    with st.expander("Fix a mistake (Edit or Delete)", expanded=False):
        st.warning("Only open this if you entered something wrong. Deleting removes the record for good.")
        history = load_live_history()
        if not history:
            st.info("Nothing to edit or delete yet.")
        else:
            hist_df = pd.DataFrame(history).reset_index().rename(columns={"index": "Row_ID"})
            st.write("**Current records**")
            st.dataframe(
                hist_df[["Row_ID", "Date", "Description", "Supplier", "Quantity", "Price", "Category", "Notes"]],
                use_container_width=True
            )
            action = st.radio(
                "What do you want to do?",
                ["Delete a record", "Edit a record"],
                horizontal=True,
                key="edit_delete_action"
            )
            row_id = st.number_input(
                "Enter Row_ID",
                min_value=0,
                max_value=max(0, len(hist_df) - 1),
                step=1,
                key="edit_delete_row_id"
            )
            if action == "Delete a record":
                st.error("This will permanently remove the record from the Price Tracker.")
                confirm = st.checkbox("Yes, I want to delete this record")
                if st.button("Delete This Record", type="primary", disabled=not confirm):
                    new_history = [rec for i, rec in enumerate(history) if i != row_id]
                    success = save_live_history(new_history)
                    if success:
                        st.success(f"Row {row_id} deleted.")
                        st.balloons()
                        st.rerun()
                    else:
                        st.error("Another user is currently saving. Please try again in a few seconds.")
            else:
                if 0 <= row_id < len(history):
                    current = history[row_id]
                    st.write("**Change the values below**")
                    col1, col2 = st.columns(2)
                    with col1:
                        new_desc = st.text_input("Product Name", value=current.get("Description", ""), key="edit_desc")
                        new_supplier = st.text_input("Supplier", value=current.get("Supplier", ""), key="edit_sup")
                        new_qty = st.number_input("Quantity", min_value=0.0, value=float(current.get("Quantity", 1)), key="edit_qty")
                    with col2:
                        new_price = st.number_input("Unit Price (KES)", min_value=0.0, value=float(current.get("Price", 0)), key="edit_price")
                        new_date = st.text_input("Date (YYYY-MM-DD)", value=str(current.get("Date", ""))[:10], key="edit_date")
                        cat_list = ["DRUG", "CONSUMABLE", "LAB", "THEATRE", "OTHER"]
                        current_cat = current.get("Category", "DRUG")
                        cat_index = cat_list.index(current_cat) if current_cat in cat_list else 0
                        new_category = st.selectbox("Category", cat_list, index=cat_index, key="edit_cat")
                    new_notes = st.text_area("Notes", value=current.get("Notes", ""), key="edit_notes")
                    if st.button("Save Changes", type="primary"):
                        history[row_id] = {
                            "Date": new_date,
                            "Description": new_desc.upper().strip(),
                            "Supplier": new_supplier.upper().strip(),
                            "Category": new_category,
                            "Quantity": float(new_qty),
                            "Price": float(new_price),
                            "Amount": float(new_qty) * float(new_price),
                            "Notes": new_notes,
                            "Registered_On": current.get("Registered_On", datetime.now().strftime("%Y-%m-%d %H:%M"))
                        }
                        success = save_live_history(history)
                        if success:
                            st.success(f"Row {row_id} updated.")
                            st.balloons()
                            st.rerun()
                        else:
                            st.error("Another user is currently saving. Please try again in a few seconds.")
                else:
                    st.warning("Invalid Row_ID")

# PAGE 3: View Product History
elif menu == "View Product History":
    st.subheader("View Product History")
    live_history = load_live_history()
    live_products = []
    if live_history:
        live_df = pd.DataFrame(live_history)
        live_products = live_df["Description"].unique().tolist()
    all_products_for_dropdown = sorted(list(set(get_all_known_products() + live_products)))
    selected_product = st.selectbox(
        "Select Product",
        options=all_products_for_dropdown,
        index=None,
        placeholder="Type to search or select a product..."
    )
    if selected_product:
        st.markdown(f"**Selected Product:** {selected_product}")

        product_category = get_product_category(selected_product)
        st.info(f"**Category:** {product_category}")

        if selected_product in res["product_supplier_history"]:
            st.write("**History from original records**")
            summary = pd.DataFrame(res["product_supplier_history"][selected_product]["summary"])
            details = pd.DataFrame(res["product_supplier_history"][selected_product]["details"])
            st.write("Summary by Supplier")
            st.dataframe(summary, use_container_width=True)
            st.write("Detailed Transactions")
            st.dataframe(details, use_container_width=True)
            st.download_button(
                label="Download Original History (Excel)",
                data=to_excel_download(details, "original_history.xlsx"),
                file_name=f"Original_History_{selected_product[:40]}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        if live_history:
            live_df = pd.DataFrame(live_history)
            product_live = live_df[live_df["Description"] == selected_product].sort_values("Date")
            if len(product_live) > 0:
                st.write("**Newly recorded purchases**")
                st.dataframe(product_live, use_container_width=True)
                live_summary = (
                    product_live.groupby("Supplier")
                    .agg(
                        Times_Bought=("Price", "count"),
                        Avg_Price=("Price", "mean"),
                        Min_Price=("Price", "min"),
                        Max_Price=("Price", "max"),
                        Total_Qty=("Quantity", "sum")
                    )
                    .round(2)
                    .reset_index()
                )
                st.write("Summary by Supplier")
                st.dataframe(live_summary, use_container_width=True)
                st.download_button(
                    label="Download Live History (Excel)",
                    data=to_excel_download(product_live, "live_history.xlsx"),
                    file_name=f"Live_History_{selected_product[:40]}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            else:
                if selected_product not in res["product_supplier_history"]:
                    st.info("No history found for this product yet.")
        else:
            if selected_product not in res["product_supplier_history"]:
                st.info("No history found for this product yet.")

# PAGE 4: Search Products
elif menu == "Search Products":
    st.subheader("Search Products")
    keyword = st.text_input("Type part of the product name")
    all_known = get_all_known_products()
    results = [p for p in all_known if keyword.upper() in p] if keyword else all_known[:100]
    st.write(f"Showing {len(results)} products")
    st.dataframe(pd.DataFrame({"Product": results}), use_container_width=True)

# PAGE 5: New Products & Reports
elif menu == "New Products & Reports":
    st.subheader("New Products & Reports")
    history = load_live_history()
    if history:
        df = pd.DataFrame(history)
        st.write("**All recorded purchases**")
        st.dataframe(df, use_container_width=True)
        st.download_button(
            "Download Full History (Excel)",
            data=to_excel_download(df, "full_history.xlsx"),
            file_name="Full_Live_Purchase_History.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        new_prods = df[~df["Description"].isin(get_all_known_products())]
        if len(new_prods) > 0:
            st.write("**New products only**")
            st.dataframe(new_prods, use_container_width=True)
            st.download_button(
                "Download New Products Report",
                data=to_excel_download(new_prods, "new_products.xlsx"),
                file_name="New_Products_Report.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
    else:
        st.info("No purchases have been recorded yet.")

# PAGE 6: Most Frequent Products
elif menu == "Most Frequent Products":
    st.subheader("Most Frequently Purchased Products")
    st.caption("Products ranked by how many times they have been purchased (Original + Live history). You can view All Time, by Year, or by Quarter. Category is auto-detected.")

    all_records = []

    # Original data
    for product, data in res["product_supplier_history"].items():
        for row in data.get("details", []):
            date_str = str(row.get("Date", "")).strip()
            try:
                if len(date_str) >= 10:
                    dt = pd.to_datetime(date_str[:10], errors="coerce")
                else:
                    dt = pd.to_datetime(date_str, errors="coerce")
            except:
                dt = pd.NaT

            all_records.append({
                "Description": str(product).upper().strip(),
                "Supplier": str(row.get("Supplier", "")).upper().strip(),
                "Quantity": float(row.get("Quantity", 0) or 0),
                "Price": float(row.get("Price", 0) or 0),
                "Date": dt,
                "Source": "Original"
            })

    # Live data
    live = load_live_history()
    for rec in live:
        date_str = str(rec.get("Date", "")).strip()
        try:
            if len(date_str) >= 10:
                dt = pd.to_datetime(date_str[:10], errors="coerce")
            else:
                dt = pd.to_datetime(date_str, errors="coerce")
        except:
            dt = pd.NaT

        all_records.append({
            "Description": str(rec.get("Description", "")).upper().strip(),
            "Supplier": str(rec.get("Supplier", "")).upper().strip(),
            "Quantity": float(rec.get("Quantity", 0) or 0),
            "Price": float(rec.get("Price", 0) or 0),
            "Date": dt,
            "Source": "Live"
        })

    if not all_records:
        st.info("No purchases recorded yet (neither original nor live).")
    else:
        df = pd.DataFrame(all_records)
        df = df.dropna(subset=["Date"])

        if df.empty:
            st.warning("No valid dates found in the records.")
        else:
            # ---------- Filter controls ----------
            view_mode = st.radio(
                "View Mode",
                ["All Time", "By Year", "By Quarter"],
                horizontal=True
            )

            filtered_df = df.copy()

            if view_mode == "By Year":
                available_years = sorted(df["Date"].dt.year.dropna().unique(), reverse=True)
                if available_years:
                    selected_year = st.selectbox("Select Year", available_years)
                    filtered_df = df[df["Date"].dt.year == selected_year]
                else:
                    st.warning("No years available.")
                    filtered_df = pd.DataFrame()

            elif view_mode == "By Quarter":
                df["YearQuarter"] = df["Date"].dt.to_period("Q").astype(str)
                available_quarters = sorted(df["YearQuarter"].dropna().unique(), reverse=True)

                if available_quarters:
                    selected_quarter = st.selectbox("Select Quarter (e.g. 2025Q3)", available_quarters)
                    filtered_df = df[df["YearQuarter"] == selected_quarter]
                else:
                    st.warning("No quarters available.")
                    filtered_df = pd.DataFrame()

            # ---------- Summary table ----------
            if filtered_df.empty:
                st.info("No purchases found for the selected period.")
            else:
                summary = (
                    filtered_df.groupby("Description")
                    .agg(
                        Times_Purchased=("Price", "count"),
                        Total_Quantity=("Quantity", "sum"),
                        Average_Price=("Price", "mean"),
                        Min_Price=("Price", "min"),
                        Max_Price=("Price", "max"),
                        Last_Purchased=("Date", "max"),
                        Suppliers=("Supplier", lambda x: ", ".join(sorted(set([s for s in x if s]))))
                    )
                    .round(2)
                    .reset_index()
                    .sort_values("Times_Purchased", ascending=False)
                )

                # Add Category
                summary["Category"] = summary["Description"].apply(get_product_category)

                # Reorder columns
                cols = ["Description", "Category", "Times_Purchased", "Total_Quantity",
                        "Average_Price", "Min_Price", "Max_Price", "Last_Purchased", "Suppliers"]
                summary = summary[cols]

                summary["Last_Purchased"] = summary["Last_Purchased"].dt.strftime("%Y-%m-%d")

                # Category filter dropdown
                category_filter = st.selectbox(
                    "Filter by Category",
                    options=["All Categories"] + sorted(summary["Category"].unique().tolist()),
                    index=0
                )

                if category_filter != "All Categories":
                    summary = summary[summary["Category"] == category_filter]

                # Search
                search = st.text_input("Search product name", placeholder="Type to filter...")
                if search:
                    summary = summary[summary["Description"].str.contains(search.upper(), na=False)]

                st.write(f"Showing **{len(summary)}** products for the selected period")
                st.dataframe(summary, use_container_width=True)

                st.download_button(
                    "Download Frequency Report (Excel)",
                    data=to_excel_download(summary, "frequent_products.xlsx"),
                    file_name=f"Most_Frequent_Products_{view_mode.replace(' ', '_')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

                st.markdown("---")
                st.markdown("### Detailed breakdown by supplier")
                selected_for_detail = st.selectbox(
                    "Select a product to see how many times it was bought from each supplier",
                    options=summary["Description"].tolist(),
                    index=None,
                    placeholder="Choose a product..."
                )
                if selected_for_detail:
                    detail = (
                        filtered_df[filtered_df["Description"] == selected_for_detail]
                        .groupby("Supplier")
                        .agg(
                            Times_Bought=("Price", "count"),
                            Total_Quantity=("Quantity", "sum"),
                            Average_Price=("Price", "mean"),
                            Min_Price=("Price", "min"),
                            Max_Price=("Price", "max"),
                            Last_Bought=("Date", "max")
                        )
                        .round(2)
                        .reset_index()
                        .sort_values("Times_Bought", ascending=False)
                    )
                    detail["Last_Bought"] = detail["Last_Bought"].dt.strftime("%Y-%m-%d")
                    st.write(f"**{selected_for_detail}** – purchases by supplier")
                    st.dataframe(detail, use_container_width=True)
