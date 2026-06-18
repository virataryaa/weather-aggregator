@echo off
REM Launch Weather Aggregator Streamlit dashboard
set BASE=%~dp0..
python -m streamlit run "%BASE%\Dashboard\app.py" --server.port 8511
