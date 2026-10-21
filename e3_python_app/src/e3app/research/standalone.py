"""Generic Streamlit entry point, independent of any E3 resource."""

import streamlit as st

from e3app.research.ui import render_research_workbench

st.set_page_config(page_title="Protein research workbench", layout="wide")
render_research_workbench()
