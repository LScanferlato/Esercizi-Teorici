#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V2 — Generatore PDF con modello idraulico/energetico esteso
per trasferimento di acqua di mare da Tripoli verso il Sahara libico.

Estensioni rispetto alla V1:
1) Perdite di carico Darcy–Weisbach per tratta.
2) Diametri di condotta parametrizzabili.
3) Tubazioni multiple in parallelo.
4) Modello energetico giorno/notte con accumulo (battery-like,
   espresso in energia e potenza equivalenti).
5) Report PDF con scenario matrix, formule e sensibilità.

NOTA IMPORTANTE
----------------
Questo è uno script di scouting tecnico / pre-fattibilità.
Non è un progetto esecutivo e non sostituisce:
- studio topografico e altimetrico di dettaglio,
- tracciato reale della pipeline,
- analisi transitorie (colpo d'ariete),
- NPSH / cavitazione,
- studio geotecnico,
- criterio reale di dispatch energetico,
- progetto elettromeccanico / grid connection / storage.

Il modello usa una semplificazione: la linea Tripoli -> destinazione viene
suddivisa in stazioni equispaziate, con salti geometrici nominali di 100 m.
Le perdite di carico di ogni tratta sono calcolate sulle condotte in parallelo.
Il fabbisogno fotovoltaico è costruito su bilancio energetico annuo e su
copertura giornaliera con accumulo per le ore non solari.
"""

import math
from statistics import mean
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
    Image,
)
import matplotlib.pyplot as plt

# =====================================================================
# 1) DATI DI BASE / FONTI USATE COME INPUT DEL MODELLO
# =====================================================================
# I numeri qui sotto ricalcano gli input della V1 e aggiungono parametri
# di progetto per idraulica e storage.
INPUTS = {
    # Dato di volume di riferimento
    'lake_garda_volume_m3': 49e9,

    # Quote di riferimento (solo contestuali)
    'tripoli_elev_m': 17.0,
    'ghat_elev_m': 668.0,

    # Coordinate geografiche
    'tripoli_coords': (32.87519, 13.18746),
    'dest_coords': (21.37870157633891, 10.270993519681898),

    # Resa FV stagionale per 1 kWp installato [kWh/giorno]
    'pv_tripoli': {'summer': 8.32, 'autumn': 5.16, 'winter': 4.01, 'spring': 6.99},
    'pv_sabha':   {'summer': 8.63, 'autumn': 5.81, 'winter': 4.99, 'spring': 7.77},
    'pv_taj':     {'summer': 8.78, 'autumn': 6.31, 'winter': 5.44, 'spring': 8.22},

    # Pannello FV usato per il conteggio fisico
    'panel_p_w': 550.0,
    'panel_len_m': 2.278,
    'panel_wid_m': 1.133,

    # Parametri fluidodinamici semplificati
    # (ordine di grandezza; acqua di mare trattata qui ~ acqua)
    'rho_kg_m3': 1000.0,
    'mu_pa_s': 1.0e-3,       # viscosità dinamica ordine di grandezza
    'g_m_s2': 9.81,

    # Rugosità assoluta equivalente condotta [m]
    # valore generico di scouting (acciaio / grande condotta industriale)
    'pipe_roughness_m': 4.5e-5,

    # Perdite localizzate aggregate per tratta: K_tot * v^2/(2g)
    # valore ipotetico aggregato per check-valves, curve, ingressi/uscite,
    # apparecchiature, raccordi. Può essere modificato facilmente.
    'minor_loss_K_total_per_segment': 8.0,

    # Rendimento gruppo di pompaggio complessivo
    'pump_eta_options': [0.80, 0.70],

    # Prevalenze geometriche totali scenario
    'static_head_options_m': [700, 800, 900],

    # Salto geometrico per stazione
    'station_lift_m': 100.0,

    # Scenari di numero condotte parallele e diametro singola condotta
    'parallel_pipeline_options': [6, 8, 10, 12],
    'diameter_options_m': [6.0, 8.0, 10.0, 12.0],

    # Modello storage / solar day-night
    # Si usa la resa media giornaliera specifica per dedurre le ore equivalenti
    # di sole (full sun hours) del sito base.
    'pv_base_site': 'Sabha',
    'battery_roundtrip_efficiency': 0.88,
    'battery_depth_of_discharge': 0.85,
    'battery_backup_margin': 1.15,

    # Nome file output
    'pdf_output': 'modello_pompaggio_tripoli_sahara_V2.pdf',
}
INPUTS['panel_area_m2'] = INPUTS['panel_len_m'] * INPUTS['panel_wid_m']

# =====================================================================
# 2) FUNZIONI DI SUPPORTO
# =====================================================================
def haversine_km(point_a, point_b):
    """Distanza geodetica in linea d'aria tra due punti (lat, lon)."""
    R = 6371.0
    lat1, lon1 = map(math.radians, point_a)
    lat2, lon2 = map(math.radians, point_b)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    x = math.sin(dlat / 2.0) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
    return 2 * R * math.asin(math.sqrt(x))


def avg_daily_yield(seasonal_dict):
    """Media dei 4 valori stagionali [kWh/giorno per kWp]."""
    return sum(seasonal_dict.values()) / 4.0


def fmt(value, nd=2):
    """Formato numerico italiano."""
    return f"{value:,.{nd}f}".replace(',', 'X').replace('.', ',').replace('X', '.')


def reynolds_number(rho, velocity, diameter, mu):
    """Numero di Reynolds."""
    return rho * velocity * diameter / mu


def swamee_jain_friction_factor(re, roughness, diameter):
    """
    Fattore di attrito Darcy–Weisbach via formula esplicita di Swamee–Jain.
    Usabile nel regime turbolento pienamente / moderatamente rugoso.
    Per re molto bassi si usa f = 64/Re.
    """
    if re <= 0:
        return float('nan')
    if re < 2000:
        return 64.0 / re
    return 0.25 / (math.log10(roughness / (3.7 * diameter) + 5.74 / (re ** 0.9)) ** 2)


def darcy_weisbach_head_loss(f, length_m, diameter_m, velocity_m_s, g):
    """Perdita di carico distribuita Darcy–Weisbach [m]."""
    return f * (length_m / diameter_m) * (velocity_m_s ** 2) / (2.0 * g)


def minor_head_loss(K_total, velocity_m_s, g):
    """Perdita di carico localizzata aggregata [m]."""
    return K_total * (velocity_m_s ** 2) / (2.0 * g)


# =====================================================================
# 3) PRE-CALCOLI GLOBALI
# =====================================================================
rho = INPUTS['rho_kg_m3']
mu = INPUTS['mu_pa_s']
g = INPUTS['g_m_s2']
roughness = INPUTS['pipe_roughness_m']
K_minor = INPUTS['minor_loss_K_total_per_segment']

# Volume totale = doppio Lago di Garda
V_total_m3 = 2.0 * INPUTS['lake_garda_volume_m3']

# Tempo annuo e portata media
T_seconds = 365 * 24 * 3600
Q_total_m3_s = V_total_m3 / T_seconds

# Distanza geodetica input -> output (non tracciato reale)
L_total_km = haversine_km(INPUTS['tripoli_coords'], INPUTS['dest_coords'])
L_total_m = L_total_km * 1000.0

# Rese specifiche annue da dati stagionali [kWh/kWp/anno]
pv_yields = {
    'Tripoli': avg_daily_yield(INPUTS['pv_tripoli']) * 365.0,
    'Sabha':   avg_daily_yield(INPUTS['pv_sabha']) * 365.0,
    'At Taj':  avg_daily_yield(INPUTS['pv_taj']) * 365.0,
}
base_site = INPUTS['pv_base_site']
base_pv_yield = pv_yields[base_site]
base_sun_hours_per_day = avg_daily_yield(INPUTS['pv_sabha'])  # ~ full-sun-hours equivalenti

# Ore giorno/notte equivalenti usate per il modello storage
sun_hours_day = base_sun_hours_per_day
night_hours = max(24.0 - sun_hours_day, 0.0)


# =====================================================================
# 4) MODELLO V2: IDRAULICA + PARALLEL PIPELINES + STORAGE
# =====================================================================
scenario_results = []

for H_static_total_m in INPUTS['static_head_options_m']:
    stations = int(round(H_static_total_m / INPUTS['station_lift_m']))
    static_head_actual_m = stations * INPUTS['station_lift_m']
    segment_length_m = L_total_m / stations

    for n_parallel in INPUTS['parallel_pipeline_options']:
        # Ogni pipeline gestisce una portata uguale Q_total / n_parallel
        Q_per_pipe = Q_total_m3_s / n_parallel

        for diameter_m in INPUTS['diameter_options_m']:
            area_pipe = math.pi * (diameter_m ** 2) / 4.0
            velocity = Q_per_pipe / area_pipe
            re = reynolds_number(rho, velocity, diameter_m, mu)
            f = swamee_jain_friction_factor(re, roughness, diameter_m)

            # Perdite distribuite per singola tratta/stazione
            hf_major_segment_m = darcy_weisbach_head_loss(f, segment_length_m, diameter_m, velocity, g)
            hf_minor_segment_m = minor_head_loss(K_minor, velocity, g)
            hf_total_segment_m = hf_major_segment_m + hf_minor_segment_m

            # Prevalenza totale che vede la stazione = salto statico + perdite di tratta
            head_per_station_m = INPUTS['station_lift_m'] + hf_total_segment_m
            total_dynamic_head_m = stations * head_per_station_m

            # Potenza idraulica ideale totale
            P_hydraulic_total_W = rho * g * Q_total_m3_s * total_dynamic_head_m
            E_hydraulic_total_kWh_year = P_hydraulic_total_W / 1000.0 * 8760.0

            for eta_pump in INPUTS['pump_eta_options']:
                # Potenza elettrica media totale assorbita dai pompaggi
                P_electric_total_W = P_hydraulic_total_W / eta_pump
                P_electric_station_W = (rho * g * Q_total_m3_s * head_per_station_m) / eta_pump
                E_electric_total_kWh_year = E_hydraulic_total_kWh_year / eta_pump

                # -----------------------------------------------------------------
                # Dimensionamento FV annuo: energia annua / resa annua specifica
                # -----------------------------------------------------------------
                pv_required_kWp_annual = E_electric_total_kWh_year / base_pv_yield

                # -----------------------------------------------------------------
                # Modello giorno/notte con accumulo
                # -----------------------------------------------------------------
                avg_power_MW = P_electric_total_W / 1e6
                daily_energy_MWh = avg_power_MW * 24.0

                # Durante le ore non solari si richiede storage energetico.
                # Energia notturna da fornire al carico:
                night_energy_MWh_load = avg_power_MW * night_hours

                # Energia nominale DC equivalente necessaria nello storage,
                # tenendo conto di roundtrip efficiency, DoD e margine.
                battery_nominal_MWh = (
                    night_energy_MWh_load
                    / INPUTS['battery_roundtrip_efficiency']
                    / INPUTS['battery_depth_of_discharge']
                    * INPUTS['battery_backup_margin']
                )

                # Potenza di erogazione storage: almeno pari alla potenza media del carico
                battery_power_MW = avg_power_MW

                # Energia che il FV deve generare ogni giorno durante le ore solari
                # per coprire sia il carico diretto nelle ore di sole, sia la quota da accumulare
                energy_to_generate_in_solar_window_MWh_day = (
                    avg_power_MW * sun_hours_day
                    + night_energy_MWh_load / INPUTS['battery_roundtrip_efficiency']
                )

                # Potenza FV richiesta per coprire la giornata in sole sun-hours/giorno
                pv_required_MWp_daynight = energy_to_generate_in_solar_window_MWh_day / sun_hours_day

                # La potenza FV finale viene scelta come max tra criterio annuo e criterio giorno/notte
                pv_required_MWp = max(pv_required_kWp_annual / 1000.0, pv_required_MWp_daynight)
                pv_required_GWp = pv_required_MWp / 1000.0

                # Conteggio pannelli e impronta geometrica moduli
                panel_count = (pv_required_MWp * 1e6) / INPUTS['panel_p_w']
                panels_million = panel_count / 1e6
                panel_area_km2 = panel_count * INPUTS['panel_area_m2'] / 1e6
                row_long_km = panel_count * INPUTS['panel_len_m'] / 1000.0
                row_short_km = panel_count * INPUTS['panel_wid_m'] / 1000.0

                scenario_results.append({
                    'H_static_total_m': static_head_actual_m,
                    'stations': stations,
                    'segment_length_km': segment_length_m / 1000.0,
                    'n_parallel': n_parallel,
                    'diameter_m': diameter_m,
                    'Q_per_pipe_m3_s': Q_per_pipe,
                    'velocity_m_s': velocity,
                    'Re': re,
                    'friction_factor': f,
                    'hf_major_segment_m': hf_major_segment_m,
                    'hf_minor_segment_m': hf_minor_segment_m,
                    'hf_total_segment_m': hf_total_segment_m,
                    'head_per_station_m': head_per_station_m,
                    'total_dynamic_head_m': total_dynamic_head_m,
                    'eta_pump': eta_pump,
                    'P_electric_total_GW': P_electric_total_W / 1e9,
                    'P_electric_station_GW': P_electric_station_W / 1e9,
                    'E_electric_total_TWh_year': E_electric_total_kWh_year / 1e9,
                    'pv_required_GWp': pv_required_GWp,
                    'battery_nominal_GWh': battery_nominal_MWh / 1000.0,
                    'battery_power_GW': battery_power_MW / 1000.0,
                    'panels_million': panels_million,
                    'panel_area_km2': panel_area_km2,
                    'row_long_km': row_long_km,
                    'row_short_km': row_short_km,
                })


# =====================================================================
# 5) SCELTA CASE BASE V2
# =====================================================================
# Criterio trasparente: scelta di uno scenario centrale leggibile.
# Static head = 800 m, n_parallel = 10, D = 10 m, eta_pump = 80%
base_candidates = [
    row for row in scenario_results
    if row['H_static_total_m'] == 800
    and row['n_parallel'] == 10
    and abs(row['diameter_m'] - 10.0) < 1e-9
    and abs(row['eta_pump'] - 0.80) < 1e-9
]
base = base_candidates[0] if base_candidates else scenario_results[0]


# =====================================================================
# 6) GRAFICI V2
# =====================================================================
# Grafico A: velocità vs diametro per diversi numeri di linee parallele
plt.figure(figsize=(8, 4.8))
for n_parallel in INPUTS['parallel_pipeline_options']:
    xs = []
    ys = []
    for diameter_m in INPUTS['diameter_options_m']:
        Q_per_pipe = Q_total_m3_s / n_parallel
        area = math.pi * diameter_m ** 2 / 4.0
        v = Q_per_pipe / area
        xs.append(diameter_m)
        ys.append(v)
    plt.plot(xs, ys, marker='o', label=f'{n_parallel} linee')
plt.xlabel('Diametro singola condotta [m]')
plt.ylabel('Velocità media nel tubo [m/s]')
plt.title('Sensibilità velocità / diametro / numero di condotte parallele')
plt.grid(True, alpha=0.25)
plt.legend()
plt.tight_layout()
plt.savefig('v2_chart_velocity.png', dpi=180)
plt.close()

# Grafico B: perdite di carico per segmento per il caso H=800m, eta=80%
plt.figure(figsize=(8, 4.8))
sel = [
    row for row in scenario_results
    if row['H_static_total_m'] == 800 and abs(row['eta_pump'] - 0.80) < 1e-9
]
labels = [f"N{row['n_parallel']}-D{int(row['diameter_m'])}" for row in sel]
loss_vals = [row['hf_total_segment_m'] for row in sel]
plt.bar(range(len(loss_vals)), loss_vals, color='#4c78a8')
plt.xticks(range(len(loss_vals)), labels, rotation=45, ha='right')
plt.ylabel('Perdita di carico per tratta [m]')
plt.title('Perdita di carico Darcy–Weisbach + locali (H statico = 800 m, η = 80%)')
plt.tight_layout()
plt.savefig('v2_chart_losses.png', dpi=180)
plt.close()

# Grafico C: Potenza FV e storage per il caso H=800m, eta=80%
plt.figure(figsize=(8, 4.8))
sel_sorted = sorted(sel, key=lambda x: (x['n_parallel'], x['diameter_m']))
labels2 = [f"N{row['n_parallel']}-D{int(row['diameter_m'])}" for row in sel_sorted]
pv_vals = [row['pv_required_GWp'] for row in sel_sorted]
st_vals = [row['battery_nominal_GWh'] / 10.0 for row in sel_sorted]  # scala /10 per leggibilità
x = range(len(labels2))
plt.bar(x, pv_vals, label='FV richiesta [GWp]', color='#f58518')
plt.bar(x, st_vals, label='Storage nominale [GWh] / 10', color='#54a24b', alpha=0.75)
plt.xticks(list(x), labels2, rotation=45, ha='right')
plt.title('Confronto FV / storage (H statico = 800 m, η = 80%)')
plt.legend()
plt.tight_layout()
plt.savefig('v2_chart_pv_storage.png', dpi=180)
plt.close()


# =====================================================================
# 7) PDF V2
# =====================================================================
styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name='TitleCenter', parent=styles['Title'], alignment=TA_CENTER,
                          fontName='Helvetica-Bold', fontSize=18, leading=22, spaceAfter=10))
styles.add(ParagraphStyle(name='SubTitleCenter', parent=styles['Normal'], alignment=TA_CENTER,
                          fontName='Helvetica', fontSize=10, textColor=colors.grey,
                          leading=12, spaceAfter=10))
styles.add(ParagraphStyle(name='Justify', parent=styles['BodyText'], alignment=TA_JUSTIFY,
                          fontName='Helvetica', fontSize=10, leading=14, spaceAfter=6))
styles.add(ParagraphStyle(name='Small', parent=styles['BodyText'], alignment=TA_LEFT,
                          fontName='Helvetica', fontSize=8.2, leading=10, spaceAfter=4))
styles.add(ParagraphStyle(name='Section', parent=styles['Heading2'], fontName='Helvetica-Bold',
                          fontSize=13, leading=15, textColor=colors.HexColor('#153b6b'),
                          spaceBefore=8, spaceAfter=6))
styles.add(ParagraphStyle(name='SubSection', parent=styles['Heading3'], fontName='Helvetica-Bold',
                          fontSize=11, leading=13, textColor=colors.HexColor('#1f5a99'),
                          spaceBefore=6, spaceAfter=4))

doc = SimpleDocTemplate(
    INPUTS['pdf_output'],
    pagesize=A4,
    rightMargin=1.6 * cm,
    leftMargin=1.6 * cm,
    topMargin=1.6 * cm,
    bottomMargin=1.6 * cm,
)

story = []
story.append(Paragraph(
    'V2 — Modello idraulico esteso con Darcy–Weisbach, condotte parallele e accumulo giorno/notte',
    styles['TitleCenter']))
story.append(Paragraph(
    'Trasferimento di acqua di mare da Tripoli verso il Sahara libico — script/report di pre-fattibilità',
    styles['SubTitleCenter']))

story.append(Paragraph(
    'Questa versione estende la V1 introducendo: perdite di carico distribuite Darcy–Weisbach, perdite localizzate aggregate, scenari di diametro condotta, multiple linee in parallelo e un modello di accumulo giorno/notte basato sulle ore equivalenti di sole del sito FV base. Il risultato è un report più vicino a un pre-dimensionamento ingegneristico, pur rimanendo un modello semplificato.',
    styles['Justify']))

# Sezione 1: input
story.append(Paragraph('1. Input del modello', styles['Section']))
input_rows = [
    ['Parametro', 'Valore'],
    ['Volume totale da trasferire', f"{fmt(V_total_m3,0)} m³"],
    ['Portata media annua', f"{fmt(Q_total_m3_s,2)} m³/s"],
    ['Distanza geodetica', f"{fmt(L_total_km,1)} km"],
    ['Sito FV base', base_site],
    ['Resa specifica annua FV base', f"{fmt(base_pv_yield,0)} kWh/kWp/anno"],
    ['Ore equivalenti di sole/giorno', f"{fmt(sun_hours_day,2)} h/giorno"],
    ['Ore notturne equivalenti', f"{fmt(night_hours,2)} h/giorno"],
    ['Rugosità condotta', f"{INPUTS['pipe_roughness_m']} m"],
    ['K perdite localizzate per tratta', f"{INPUTS['minor_loss_K_total_per_segment']}"],
]

tbl_inputs = Table(input_rows, colWidths=[8.0*cm, 8.2*cm])
tbl_inputs.setStyle(TableStyle([
    ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#153b6b')),
    ('TEXTCOLOR', (0,0), (-1,0), colors.white),
    ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
    ('GRID', (0,0), (-1,-1), 0.25, colors.grey),
    ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.whitesmoke, colors.HexColor('#eef3f8')]),
]))
story.append(tbl_inputs)
story.append(Spacer(1, 0.2*cm))

# Sezione 2: formule V2
story.append(Paragraph('2. Formule principali V2', styles['Section']))
for formula in [
    'Velocità in ogni condotta: <b>v = Q_pipe / A = (Q_total / N_parallel) / (πD²/4)</b>',
    'Numero di Reynolds: <b>Re = ρvD/μ</b>',
    'Fattore di attrito (Swamee–Jain): <b>f = 0,25/[log10(ε/(3,7D)+5,74/Re^0,9)]²</b>',
    'Perdita distribuita Darcy–Weisbach: <b>h_f = f(L/D)(v²/2g)</b>',
    'Perdita localizzata aggregata: <b>h_m = K(v²/2g)</b>',
    'Prevalenza per stazione: <b>H_station = H_static_station + h_f + h_m</b>',
    'Prevalenza dinamica totale: <b>H_dyn,total = N_station · H_station</b>',
    'Potenza elettrica totale: <b>P_el = ρgQH_dyn,total/η</b>',
    'Storage energia nominale: <b>E_batt = (P_avg · h_notte)/(η_rt · DoD) · margine</b>',
    'Potenza FV giorno/notte: <b>P_FV = max(E_ann/Y_FV, E_daywindow / sun_hours)</b>',
]:
    story.append(Paragraph('• ' + formula, styles['Justify']))

# Sezione 3: case base
story.append(Paragraph('3. Caso base V2', styles['Section']))
base_rows = [
    ['Parametro', 'Caso base V2'],
    ['Prevalenza statica totale', f"{base['H_static_total_m']} m"],
    ['Numero stazioni', str(base['stations'])],
    ['Lunghezza media tratta', f"{fmt(base['segment_length_km'],1)} km"],
    ['Numero condotte parallele', str(base['n_parallel'])],
    ['Diametro singola condotta', f"{fmt(base['diameter_m'],1)} m"],
    ['Portata per condotta', f"{fmt(base['Q_per_pipe_m3_s'],2)} m³/s"],
    ['Velocità in condotta', f"{fmt(base['velocity_m_s'],2)} m/s"],
    ['Reynolds', f"{fmt(base['Re'],0)}"],
    ['Fattore di attrito', f"{fmt(base['friction_factor'],4)}"],
    ['Perdita distribuita per tratta', f"{fmt(base['hf_major_segment_m'],2)} m"],
    ['Perdita localizzata per tratta', f"{fmt(base['hf_minor_segment_m'],2)} m"],
    ['Perdita totale per tratta', f"{fmt(base['hf_total_segment_m'],2)} m"],
    ['Prevalenza reale per stazione', f"{fmt(base['head_per_station_m'],2)} m"],
    ['Prevalenza dinamica totale', f"{fmt(base['total_dynamic_head_m'],2)} m"],
    ['Rendimento pompaggio', f"{int(base['eta_pump']*100)}%"],
    ['Potenza elettrica totale', f"{fmt(base['P_electric_total_GW'],2)} GW"],
    ['Potenza per stazione', f"{fmt(base['P_electric_station_GW'],2)} GW"],
    ['Energia annua totale', f"{fmt(base['E_electric_total_TWh_year'],1)} TWh/anno"],
    ['FV richiesta', f"{fmt(base['pv_required_GWp'],1)} GWp"],
    ['Storage nominale', f"{fmt(base['battery_nominal_GWh'],1)} GWh"],
    ['Potenza storage', f"{fmt(base['battery_power_GW'],2)} GW"],
    ['Pannelli da 550 W', f"{fmt(base['panels_million'],1)} milioni"],
    ['Superficie moduli', f"{fmt(base['panel_area_km2'],0)} km²"],
    ['Fila moduli lato lungo', f"{fmt(base['row_long_km'],0)} km"],
]

tbl_base = Table(base_rows, colWidths=[8.2*cm, 8.0*cm])
tbl_base.setStyle(TableStyle([
    ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#153b6b')),
    ('TEXTCOLOR', (0,0), (-1,0), colors.white),
    ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
    ('GRID', (0,0), (-1,-1), 0.25, colors.grey),
    ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.whitesmoke, colors.HexColor('#eef3f8')]),
    ('VALIGN', (0,0), (-1,-1), 'TOP'),
]))
story.append(tbl_base)
story.append(Spacer(1, 0.2*cm))

story.append(Paragraph(
    'Nel caso base V2 le perdite di carico si sommano alla prevalenza geometrica di 100 m per stazione; questo porta a una prevalenza dinamica totale superiore rispetto al modello V1. La potenza FV finale è posta come massimo tra il criterio annuo e il criterio giorno/notte, quest’ultimo necessario per includere l’energia da accumulare nelle ore non solari.',
    styles['Justify']))

# Grafici
story.append(Image('v2_chart_velocity.png', width=16.5*cm, height=9.5*cm))
story.append(Spacer(1, 0.15*cm))
story.append(Image('v2_chart_losses.png', width=16.5*cm, height=9.5*cm))
story.append(Spacer(1, 0.15*cm))
story.append(Image('v2_chart_pv_storage.png', width=16.5*cm, height=9.5*cm))

# Sezione 4: matrice sintetica selezionata
story.append(PageBreak())
story.append(Paragraph('4. Matrice sintetica scenari (H statico = 800 m, η = 80%)', styles['Section']))
subset = [
    row for row in scenario_results
    if row['H_static_total_m'] == 800 and abs(row['eta_pump'] - 0.80) < 1e-9
]
subset = sorted(subset, key=lambda x: (x['n_parallel'], x['diameter_m']))

matrix_rows = [[
    'N linee', 'D [m]', 'v [m/s]', 'hf tratta [m]', 'H dyn tot [m]',
    'P [GW]', 'FV [GWp]', 'Batt [GWh]'
]]
for row in subset:
    matrix_rows.append([
        str(row['n_parallel']),
        fmt(row['diameter_m'], 1),
        fmt(row['velocity_m_s'], 2),
        fmt(row['hf_total_segment_m'], 2),
        fmt(row['total_dynamic_head_m'], 1),
        fmt(row['P_electric_total_GW'], 2),
        fmt(row['pv_required_GWp'], 1),
        fmt(row['battery_nominal_GWh'], 1),
    ])

tbl_matrix = Table(matrix_rows, colWidths=[1.6*cm, 1.5*cm, 2.0*cm, 2.2*cm, 2.4*cm, 2.0*cm, 2.0*cm, 2.2*cm])
tbl_matrix.setStyle(TableStyle([
    ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#153b6b')),
    ('TEXTCOLOR', (0,0), (-1,0), colors.white),
    ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
    ('FONTSIZE', (0,0), (-1,-1), 8.2),
    ('GRID', (0,0), (-1,-1), 0.25, colors.grey),
    ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.whitesmoke, colors.HexColor('#eef3f8')]),
    ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
]))
story.append(tbl_matrix)
story.append(Spacer(1, 0.2*cm))

# Sezione 5: note metodologiche
story.append(Paragraph('5. Note metodologiche e limiti del modello', styles['Section']))
for bullet in [
    'Il tracciato della pipeline è assunto come distanza geodetica suddivisa equamente; una pipeline reale avrebbe sviluppo planimetrico e altimetrico differente.',
    'Le perdite localizzate sono aggregate in un singolo coefficiente K per tratta; un progetto reale richiederebbe il dettaglio di ogni organo e accessorio.',
    'Lo storage è espresso come equivalente energetico nominale. Non sono modellati degrado, temperatura, finestra di dispatch, C-rate o architetture ibride.',
    'Non sono inclusi transitori idraulici, colpi d’ariete, ridondanza, manutenzione, by-pass, avviamenti, profili orari meteo reali o disponibilità impianto.',
    'Il modello è pensato per confrontare ordini di grandezza e sensitività, non per definire una BOM o una stima CAPEX/OPEX definitiva.',
]:
    story.append(Paragraph('• ' + bullet, styles['Justify']))

# Appendice fonti (coerenti con V1 + estensioni descrittive)
story.append(Paragraph('Appendice — Fonti e parametri considerati', styles['Section']))
source_entries = [
    ('Lago di Garda: volume 49 miliardi m³', 'LTER Italia / DEIMS-SDR', 'https://www.lteritalia.it/?page_id=458'),
    ('Lago di Garda: volume 49 miliardi m³', 'DEIMS-SDR', 'https://deims.org/c713db56-373c-46cc-8828-ce8cadc4f3bb'),
    ('Tripoli: quota puntuale 17 m', 'Maplogs', 'https://elevation.maplogs.com/poi/tripoli_libya.273406.html'),
    ('Tripolitania: plateau calcarei 610–910 m', 'Topographic Map / testo geografico riportato', 'https://en-us.topographic-map.com/map-s8ldb3/Tripoli/'),
    ('Tripoli District: contesto geografico', 'Wikipedia', 'https://en.wikipedia.org/wiki/Tripoli_District,_Libya'),
    ('Ghat: quota 668 m', 'Wikipedia', 'https://en.wikipedia.org/wiki/Ghat,_Libya'),
    ('PVOUT / dati solari Libia', 'Global Solar Atlas', 'https://globalsolaratlas.info/download/libya'),
    ('Definizione PVOUT (kWh/kWp)', 'Global Solar Atlas / ArcGIS layer overview', 'https://www.arcgis.com/home/item.html?id=058f3cef28664e8c963d4c757f71c36d'),
    ('Studio World Bank Global Photovoltaic Power Potential', 'World Bank', 'https://documents1.worldbank.org/curated/en/466331592817725242/pdf/Global-Photovoltaic-Power-Potential-by-Country.pdf'),
    ('Valori stagionali FV Tripoli / Sabha / At Taj', 'profileSOLAR', 'https://profilesolar.com/countries/LY/'),
    ('Pannello 550 W — dimensioni modulo', 'AE Solar datasheet', 'https://www.ae-solar.com/documents/solar_panels/Aurora/AE_MD-144_530W-550W_Ver24.1.1.pdf'),
]
for title, org, url in source_entries:
    story.append(Paragraph(f"<b>{title}</b><br/>{org}<br/><font size=8>{url}</font>", styles['Small']))
    story.append(Spacer(1, 0.05*cm))


def add_page_num(canvas, doc_obj):
    canvas.saveState()
    canvas.setFont('Helvetica', 8)
    canvas.setFillColor(colors.grey)
    canvas.drawRightString(A4[0] - 1.6*cm, 1.0*cm, f'Pagina {doc_obj.page}')
    canvas.drawString(1.6*cm, 1.0*cm, 'Tripoli → Sahara libico — modello V2')
    canvas.restoreState()


doc.build(story, onFirstPage=add_page_num, onLaterPages=add_page_num)

print('PDF creato:', INPUTS['pdf_output'])
print('CASE BASE V2:', base)
print('Rese FV annue:', pv_yields)
print('Distanza geodetica [km]:', L_total_km)
