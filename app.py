# Hospital Procurement - Fair Price System
import streamlit as st
import joblib
import pandas as pd
import numpy as np
from datetime import datetime
import os
from io import BytesIO

st.set_page_config(page_title="Hospital Fair Price System", page_icon="🏥", layout="wide")
st.title("Hospital Procurement – Fair Price System")

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
    st.error(f"Could not load files from the price_models folder.\n\n{e}")
    st.stop()

def load_live_history():
    path = "price_models/live_purchase_history.joblib"
    if os.path.exists(path):
        return joblib.load(path)
    return []

def save_live_history(history):
    joblib.dump(history, "price_models/live_purchase_history.joblib")
    pd.DataFrame(history).to_excel("price_models/Live_Purchase_History.xlsx", index=False)

def get_all_suppliers():
    """Collect unique suppliers from original history + live history"""
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
    """Return combined historical prices for a product from original + live data"""
    description = str(description).upper().strip()
    prices = []
    suppliers = []
    # From original data
    if description in res["product_supplier_history"]:
        details = res["product_supplier_history"][description].get("details", [])
        for d in details:
            try:
                prices.append(float(d.get("Price", 0)))
                suppliers.append(str(d.get("Supplier", "")).upper())
            except:
                pass
    # From live history
    live = load_live_history()
    for rec in live:
        if str(rec.get("Description", "")).upper().strip() == description:
            try:
                prices.append(float(rec.get("Price", 0)))
                suppliers.append(str(rec.get("Supplier", "")).upper())
            except:
                pass
    return prices, suppliers

def predict_fair_price(description, quantity, supplier, month, proposed_price, category="DRUG"):
    description = str(description).upper().strip()
    supplier = str(supplier).upper().strip()
    # Get historical prices for comparison
    hist_prices, hist_suppliers = get_product_price_history(description)
    hist_median = np.median(hist_prices) if hist_prices else None
    hist_mean = np.mean(hist_prices) if hist_prices else None
    hist_min = min(hist_prices) if hist_prices else None
    hist_max = max(hist_prices) if hist_prices else None
    is_new_supplier = supplier not in [s.upper() for s in hist_suppliers]
    # Model prediction (existing logic)
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
        # Fallback to history
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
            "Previous Suppliers": list(set(hist_suppliers))
        }
    try:
        desc_enc = le_desc.transform([description])[0]
    except:
        # Fall back to history if product encoding fails
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
                "Previous Suppliers": list(set(hist_suppliers))
            }
        return predict_from_history(description, proposed_price)
    try:
        sup_enc = le_sup.transform([supplier])[0]
    except:
        sup_enc = 0  # unknown supplier
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
        result["Previous Suppliers"] = list(set(hist_suppliers))
        # Extra warning if new supplier is significantly higher than historical
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
    st.markdown("### Result")
    st.write(f"**Product Group:** {result.get('Product Group', 'N/A')}")
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
        if result.get("Previous Suppliers"):
            st.write("**Previous suppliers:** " + ", ".join(result["Previous Suppliers"]))
    recommendation = result.get("Recommendation", "")
    if "HIGH" in recommendation:
        st.error(f"**Recommendation:** {recommendation}")
    elif "MEDIUM" in recommendation:
        st.warning(f"**Recommendation:** {recommendation}")
    else:
        st.success(f"**Recommendation:** {recommendation}")

# Menu
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
    selected_product = st.selectbox(
        "Select Product",
        options=res["all_known_products"],
        index=None,
        placeholder="Type to search or select a product..."
    )
    new_product = st.text_input("Or type a new product name (leave empty if you selected above)")
    product_to_use = new_product.strip().upper() if new_product.strip() else selected_product
    if product_to_use:
        st.markdown(f"**Selected Product:** {product_to_use}")
        # Show previous suppliers for this product
        if product_to_use in res["product_supplier_history"]:
            summary_df = pd.DataFrame(res["product_supplier_history"][product_to_use]["summary"])
            st.write("**Suppliers who previously supplied this product**")
            st.dataframe(summary_df, use_container_width=True)
        # Also show live history suppliers
        live = load_live_history()
        live_df = pd.DataFrame(live) if live else pd.DataFrame()
        if len(live_df) > 0:
            live_for_prod = live_df[live_df["Description"] == product_to_use]
            if len(live_for_prod) > 0:
                st.write("**Recent live purchases for this product**")
                st.dataframe(live_for_prod[["Date", "Supplier", "Quantity", "Price"]].sort_values("Date", ascending=False), use_container_width=True)
        # Supplier selection (searchable + new)
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
                    product_to_use, quantity, selected_supplier, month, proposed_price
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
    all_products = sorted(list(set(res["all_known_products"] + live_products)))
    # Price Tracker
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
    # Add new purchase
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

        # ===== MODIFIED SUPPLIER SECTION =====
        # Searchable supplier dropdown (all known + new) + last suppliers of this product
        all_sups = get_all_suppliers()

        # Get suppliers who previously supplied this product (original + live)
        previous_suppliers_for_product = []
        if product_to_save in res["product_supplier_history"]:
            for row in res["product_supplier_history"][product_to_save].get("summary", []):
                previous_suppliers_for_product.append(str(row.get("Supplier", "")).upper().strip())
        live = load_live_history()
        for rec in live:
            if str(rec.get("Description", "")).upper().strip() == product_to_save:
                previous_suppliers_for_product.append(str(rec.get("Supplier", "")).upper().strip())
        previous_suppliers_for_product = sorted(list(set([s for s in previous_suppliers_for_product if s])))

        # Show last suppliers first in the dropdown
        if previous_suppliers_for_product:
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
        # ===== END OF MODIFIED SUPPLIER SECTION =====

        col1, col2 = st.columns(2)
        with col1:
            qty = st.number_input("Quantity", min_value=1.0, value=1.0, step=1.0, key="tracker_qty")
            price = st.number_input("Unit Price (KES)", min_value=0.0, value=0.0, step=0.01, key="tracker_price")
        with col2:
            purchase_date = st.date_input("Date of Purchase", value=datetime.now(), key="tracker_date")
            category = st.selectbox("Category", ["DRUG", "CONSUMABLE", "LAB", "THEATRE", "OTHER"], key="tracker_cat")
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
                save_live_history(history)
                st.success(f"Saved. {product_to_save} now has {already+1} price record(s).")
                st.balloons()
                st.rerun()
    # Edit / Delete – only open when you need to fix a mistake
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
                    save_live_history(new_history)
                    st.success(f"Row {row_id} deleted.")
                    st.balloons()
                    st.rerun()
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
                        save_live_history(history)
                        st.success(f"Row {row_id} updated.")
                        st.balloons()
                        st.rerun()
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
    results = [p for p in res["all_known_products"] if keyword.upper() in p] if keyword else res["all_known_products"][:100]
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
        new_prods = df[~df["Description"].isin(res["all_known_products"])]
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

# PAGE 6: Most Frequently Purchased Products  (MODIFIED)
elif menu == "Most Frequent Products":
    st.subheader("Most Frequently Purchased Products")
    st.caption("Products ranked by how many times they have been purchased (live history). Shows quantity, price range, suppliers and last purchase date.")

    history = load_live_history()
    if not history:
        st.info("No purchases recorded yet.")
    else:
        df = pd.DataFrame(history)

        # Overall frequency summary
        summary = (
            df.groupby("Description")
            .agg(
                Times_Purchased=("Price", "count"),
                Total_Quantity=("Quantity", "sum"),
                Average_Price=("Price", "mean"),
                Min_Price=("Price", "min"),
                Max_Price=("Price", "max"),
                Last_Purchased=("Date", "max"),
                Suppliers=("Supplier", lambda x: ", ".join(sorted(set(x))))
            )
            .round(2)
            .reset_index()
            .sort_values("Times_Purchased", ascending=False)
        )

        # Search filter
        search = st.text_input("Search product name", placeholder="Type to filter...")
        if search:
            summary = summary[summary["Description"].str.contains(search.upper(), na=False)]

        st.write(f"Showing {len(summary)} products")
        st.dataframe(summary, use_container_width=True)

        st.download_button(
            "Download Frequency Report (Excel)",
            data=to_excel_download(summary, "frequent_products.xlsx"),
            file_name="Most_Frequent_Products.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

        # Detailed breakdown per product → per supplier
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
                df[df["Description"] == selected_for_detail]
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
            st.write(f"**{selected_for_detail}** – purchases by supplier")
            st.dataframe(detail, use_container_width=True)
