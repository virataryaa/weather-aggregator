@echo off
REM Weather Aggregator — Daily Ingestion Runner
REM Schedule this via Task Scheduler at 07:00 daily

set BASE=%~dp0..
set LOG_DIR=%BASE%\Automator\logs
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

set LOG=%LOG_DIR%\ingest_%date:~-4,4%%date:~-7,2%%date:~0,2%.txt

echo ============================================================ >> "%LOG%"
echo Weather Aggregator Ingest — %date% %time% >> "%LOG%"
echo ============================================================ >> "%LOG%"

echo. >> "%LOG%"
echo [1/3] Open-Meteo Ivory Coast Precipitation >> "%LOG%"
python "%BASE%\Ingestion\openmeteo_civ.py" >> "%LOG%" 2>&1
if %ERRORLEVEL% NEQ 0 echo ERROR in openmeteo_civ.py >> "%LOG%"

echo. >> "%LOG%"
echo [2/3] ECMWF South America Charts >> "%LOG%"
python "%BASE%\Ingestion\ecmwf_sa.py" >> "%LOG%" 2>&1
if %ERRORLEVEL% NEQ 0 echo ERROR in ecmwf_sa.py >> "%LOG%"

echo. >> "%LOG%"
echo [3/3] Maxar Brazil Ensemble >> "%LOG%"
python "%BASE%\Ingestion\maxar_brazil.py" >> "%LOG%" 2>&1
if %ERRORLEVEL% NEQ 0 echo ERROR in maxar_brazil.py >> "%LOG%"

echo. >> "%LOG%"
echo Done — %time% >> "%LOG%"
echo ============================================================ >> "%LOG%"
