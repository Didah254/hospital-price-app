# =========================================================
# Hospital Fair Price System - Complete Full Version
# =========================================================

import streamlit as st
import joblib
import pandas as pd
import numpy as np
from datetime import datetime
import os
from io import BytesIO

st.set_page_config(page_title="Hospital Fair Price System", page_icon="🏥", layout="wide")
st.title("🏥 Hospital Procurement – Fair Price System")

# -------------------------------------------------
# Load resources
# -------------------------------------------------
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

try:
    res = load_resources()
except Exception as e:
    st.error(f"Could not load files from 'price_models' folder.\n\n{e}")
    st.stop()

# -------------------------------------------------
# Live history helpers
# -------------------------------------------------
def load_live_history():
    path = "price_models/live_purchase_history.joblib"
    if os.path.exists(path):
        return joblib.load(path)
    return []

def save_live_history(history):
    joblib.dump(history, "price_models/live_purchase_history.joblib")
    pd.DataFrame(history).to_excel("price_models/Live_Purchase_History.xlsx", index=False)

# -------------------------------------------------
# Prediction functions
# -------------------------------------------------
def predict_fair_price(description, quantity, supplier, month, proposed_price, category="DRUG"):
    description = str(description).upper().strip()
    supplier = str(supplier).upper().strip()

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
        return predict_from_history(description, proposed_price)

    try:
        desc_enc = le_desc.transform([description])[0]
    except:
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

    return {
        "Product Group": group,
        "Expected fair price (KES)": round(float(expected), 2),
        "Proposed price (KES)": proposed_price,
        "Difference %": round(float(variance), 1),
        "Recommendation": status
    }

def predict_from_history(description, proposed_price):
    description = str(description).upper().strip()
    history = load_live_history()
    df = pd.DataFrame(history)
    product_df = df[df["Description"] == description]

    if len(product_df) < 3:
        return {
            "Message": f"Only {len(product_df)} purchase(s) recorded so far. Need at least 3 to give a reliable estimate.",
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
        "Recommendation": status
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

    st.markdown("### Prediction Result")
    st.write(f"**Product Group:** {result.get('Product Group', 'N/A')}")
    st.write(f"**Expected Fair Price:** KES {result.get('Expected fair price (KES)', result.get('Median price (KES)', 'N/A'))}")
    st.write(f"**Proposed Price:** KES {result.get('Proposed price (KES)', 'N/A')}")
    st.write(f"**Difference:** {result.get('Difference %', 'N/A')}%")

    recommendation = result.get("Recommendation", "")
    if "HIGH" in recommendation:
        st.error(f"**Recommendation:** {recommendation}")
    elif "MEDIUM" in recommendation:
        st.warning(f"**Recommendation:** {recommendation}")
    else:
        st.success(f"**Recommendation:** {recommendation}")

# -------------------------------------------------
# TOP DASHBOARD MENU
# -------------------------------------------------
st.markdown("---")
menu = st.selectbox(
    "Select Action",
    [
        "Check Fair Price",
        "Register Purchase",
        "View Product History",
        "Search Products",
        "New Products & Reports"
    ],
    index=0
)
st.markdown("---")

# -------------------------------------------------
# PAGE 1: Check Fair Price
# -------------------------------------------------
if menu == "Check Fair Price":
    st.subheader("Check Fair Price")

    selected_product = st.selectbox(
        "Select Product",
        options=res["all_known_products"],
        index=None,
        placeholder="Type to search or select a product..."
    )

    new_product = st.text_input("Or type a completely NEW product name (leave empty if you selected above)")
    product_to_use = new_product.strip().upper() if new_product.strip() else selected_product

    if product_to_use:
        st.markdown(f"**Selected Product:** {product_to_use}")

        if product_to_use in res["product_supplier_history"]:
            summary_df = pd.DataFrame(res["product_supplier_history"][product_to_use]["summary"])
            st.write("**Suppliers who previously supplied this product**")
            st.dataframe(summary_df, use_container_width=True)

            supplier_options = summary_df["Supplier"].tolist() + ["-- Add New Supplier --"]
            selected_supplier = st.selectbox("Select Supplier", options=supplier_options, index=None)

            if selected_supplier == "-- Add New Supplier --":
                selected_supplier = st.text_input("Enter NEW Supplier Name")
        else:
            selected_supplier = st.text_input("Supplier Name (new product)")

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
                    product_to_use, quantity, selected_supplier, month, proposed_price
                )
                show_clean_result(result)

                report_df = pd.DataFrame([result])
                excel_data = to_excel_download(report_df, "fair_price_report.xlsx")
                st.download_button(
                    label="Download this Prediction Report (Excel)",
                    data=excel_data,
                    file_name=f"Fair_Price_{product_to_use[:30]}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

# -------------------------------------------------
# PAGE 2: Register Purchase (Searchable Dropdown Version)
# -------------------------------------------------
elif menu == "Register Purchase":
    st.subheader("Register / Update Purchase Record")
    st.caption("Use this page to record the latest price of any product (old or new) from the same supplier or a new supplier.")

    # Combine original products + newly recorded products
    live_history = load_live_history()
    live_products = []
    if live_history:
        live_df = pd.DataFrame(live_history)
        live_products = live_df["Description"].unique().tolist()

    all_products = sorted(list(set(res["all_known_products"] + live_products)))

    # ---------- Product Selection ----------
    st.markdown("### 1. Select Product")
    selected_product = st.selectbox(
        "Search and select product",
        options=all_products,
        index=None,
        placeholder="Type product name to search..."
    )

    new_product = st.text_input("Or type a completely NEW product name (only if not in the list)")

    product_to_save = new_product.strip().upper() if new_product.strip() else (selected_product.upper().strip() if selected_product else "")

    if product_to_save:
        st.success(f"Product selected: **{product_to_save}**")

        # ---------- Supplier Selection ----------
        st.markdown("### 2. Select Supplier")
        previous_suppliers = []

        # Suppliers from original data
        if product_to_save in res["product_supplier_history"]:
            previous_suppliers = [row["Supplier"] for row in res["product_supplier_history"][product_to_save]["summary"]]

        # Suppliers from live history
        if live_history:
            live_df = pd.DataFrame(live_history)
            live_suppliers = live_df[live_df["Description"] == product_to_save]["Supplier"].unique().tolist()
            previous_suppliers = sorted(list(set(previous_suppliers + live_suppliers)))

        if previous_suppliers:
            supplier_options = previous_suppliers + ["-- Add New Supplier --"]
            selected_supplier = st.selectbox(
                "Search and select supplier",
                options=supplier_options,
                index=None,
                placeholder="Type supplier name to search..."
            )
            if selected_supplier == "-- Add New Supplier --":
                selected_supplier = st.text_input("Enter NEW Supplier Name")
        else:
            selected_supplier = st.text_input("Enter Supplier Name")

        # ---------- Price, Quantity, Date ----------
        st.markdown("### 3. Enter Purchase Details")
        col1, col2 = st.columns(2)
        with col1:
            qty = st.number_input("Quantity *", min_value=1.0, value=1.0, step=1.0)
            price = st.number_input("Unit Price (KES) *", min_value=0.0, value=0.0, step=0.01)
        with col2:
            purchase_date = st.date_input("Date of Purchase", value=datetime.now())
            category = st.selectbox("Category", ["DRUG", "CONSUMABLE", "LAB", "THEATRE", "OTHER"])

        notes = st.text_area("Notes (optional)", placeholder="e.g. Urgent order, discount given, etc.")

        # ---------- Save Button ----------
        if st.button("Save Purchase Record", type="primary"):
            if not product_to_save or not selected_supplier or price <= 0:
                st.warning("Please fill in Product, Supplier and a valid Price.")
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
                save_live_history(history)

                st.success("Record saved successfully!")
                st.write(f"**Product:** {product_to_save}")
                st.write(f"**Supplier:** {selected_supplier}")
                st.write(f"**Quantity:** {qty}")
                st.write(f"**Unit Price:** KES {price:,.2f}")
                st.write(f"**Date:** {purchase_date.strftime('%Y-%m-%d')}")
                st.balloons()

# -------------------------------------------------
# PAGE 3: View Product History
# -------------------------------------------------
elif menu == "View Product History":
    st.subheader("View Product History")

    live_history = load_live_history()
    live_products = []
    if live_history:
        live_df = pd.DataFrame(live_history)
        live_products = live_df["Description"].unique().tolist()

    all_products_for_dropdown = sorted(list(set(res["all_known_products"] + live_products)))

    selected_product = st.selectbox(
        "Select Product",
        options=all_products_for_dropdown,
        index=None,
        placeholder="Type to search or select a product..."
    )

    if selected_product:
        st.markdown(f"**Selected Product:** {selected_product}")

        if selected_product in res["product_supplier_history"]:
            st.write("**History from Original Records**")
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
                st.write("**Newly Recorded Purchases**")
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
                    label="Download Live History of this Product (Excel)",
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

# -------------------------------------------------
# PAGE 4: Search Products
# -------------------------------------------------
elif menu == "Search Products":
    st.subheader("Search Products")
    keyword = st.text_input("Type part of the product name")
    results = [p for p in res["all_known_products"] if keyword.upper() in p] if keyword else res["all_known_products"][:100]
    st.write(f"Showing {len(results)} products")
    st.dataframe(pd.DataFrame({"Product": results}), use_container_width=True)

# -------------------------------------------------
# PAGE 5: New Products & Reports
# -------------------------------------------------
elif menu == "New Products & Reports":
    st.subheader("New Products & Download Reports")

    history = load_live_history()
    if history:
        df = pd.DataFrame(history)

        st.write("**All Newly Recorded Purchases**")
        st.dataframe(df, use_container_width=True)

        st.download_button(
            "Download Full Live History (Excel)",
            data=to_excel_download(df, "full_history.xlsx"),
            file_name="Full_Live_Purchase_History.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

        new_prods = df[~df["Description"].isin(res["all_known_products"])]
        if len(new_prods) > 0:
            st.write("**Only New Products (not in original training data)**")
            st.dataframe(new_prods, use_container_width=True)
            st.download_button(
                "Download New Products Report",
                data=to_excel_download(new_prods, "new_products.xlsx"),
                file_name="New_Products_Report.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
    else:
        st.info("No live purchases have been recorded yet.")