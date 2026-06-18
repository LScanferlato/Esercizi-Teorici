#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generatore PDF — Modello preliminare di pompaggio a stazioni da 100 m
per trasferimento di acqua di mare da Tripoli verso il Sahara libico.

Questo script:
1) definisce i dati di base e le ipotesi del modello;
2) calcola portata, potenza, energia e dimensionamento FV equivalente;
3) produce tre grafici PNG;
4) genera un PDF in stile accademico con formule, tabelle, grafici e fonti.

Nota metodologica:
- è un modello di ordine di grandezza;
- usa scenari di prevalenza totale (700, 800, 900 m);
- usa rendimenti complessivi 80% e 70%;
- il dimensionamento fotovoltaico è un bilancio energetico annuo,
  non un progetto 24/7 con accumulo.
"""

import math
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

# ============================================================
# 1) DATI DI BASE USATI NEL MODELLO
# ============================================================
# Tutti questi numeri sono gli ingressi del modello. Alcuni derivano dalle
# fonti citate nel PDF finale; altri sono scelte progettuali esplicite
# (per esempio i salti di pompaggio e i rendimenti)
# utili per fare una stima ingegneristica preliminare.
SOURCES = {
    # Volume del Lago di Garda riportato nelle fonti consultate
    'lake_garda_volume_m3': 49e9,

    # Quota di riferimento di Tripoli usata come partenza del modello
    'tripoli_elev_m': 17.0,

    # Quota di controllo regionale (Ghat) usata come plausibility check
    'ghat_elev_m': 668.0,

    # Coordinate geografiche di origine e destinazione
    'tripoli_coords': (32.87519, 13.18746),
    'dest_coords': (21.37870157633891, 10.270993519681898),

    # Resa FV stagionale pubblicata (kWh/giorno per 1 kWp installato)
    # per tre località libiche usate per ricavare la resa annua specifica.
    'pv_tripoli': {'summer': 8.32, 'autumn': 5.16, 'winter': 4.01, 'spring': 6.99},
    'pv_sabha':   {'summer': 8.63, 'autumn': 5.81, 'winter': 4.99, 'spring': 7.77},
    'pv_taj':     {'summer': 8.78, 'autumn': 6.31, 'winter': 5.44, 'spring': 8.22},

    # Parametri del pannello FV scelto per il conteggio pannelli / lunghezza fila
    'panel_p_w': 550.0,
    'panel_len_m': 2.278,
    'panel_wid_m': 1.133,
}
SOURCES['panel_area_m2'] = SOURCES['panel_len_m'] * SOURCES['panel_wid_m']

# ============================================================
# 2) FUNZIONI DI SUPPORTO
# ============================================================
def haversine_km(point_a, point_b):
    """
    Distanza geodetica approssimata in km tra due coppie (lat, lon)
    usando la formula dell'haversine.

    Serve per stimare la distanza in linea d'aria tra Tripoli e la destinazione.
    Non rappresenta un tracciato ingegnerizzato reale di pipeline.
    """
    R = 6371.0  # raggio medio terrestre in km
    lat1, lon1 = map(math.radians, point_a)
    lat2, lon2 = map(math.radians, point_b)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    x = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))


def avg_daily_yield(seasonal_dict):
    """
    Media semplice dei quattro valori stagionali (kWh/giorno per 1 kWp).
    Da questa media si ricava una resa annua specifica semplificata.
    """
    return sum(seasonal_dict.values()) / 4.0


def fmt(value, nd=2):
    """
    Formattazione numerica in stile italiano
    (virgola decimale, punto separatore migliaia).
    """
    return f"{value:,.{nd}f}".replace(',', 'X').replace('.', ',').replace('X', '.')


# ============================================================
# 3) IPOTESI FISICHE E DI PROGETTO
# ============================================================
# Densità: per semplicità acqua di mare ~ acqua dolce in questa stima di primo livello
rho = 1000.0   # kg/m³
# Accelerazione di gravità
G = 9.81       # m/s²

# Volume totale da trasferire: doppio del Lago di Garda
V_total_m3 = 2 * SOURCES['lake_garda_volume_m3']

# Tempo totale del trasferimento: 1 anno
T_seconds = 365 * 24 * 3600

# Portata media richiesta
Q_m3_s = V_total_m3 / T_seconds

# Distanza geodetica Tripoli -> punto finale
L_km = haversine_km(SOURCES['tripoli_coords'], SOURCES['dest_coords'])

# Scenari di prevalenza totale (modellati per ordini di grandezza)
head_scenarios_m = [700, 800, 900]

# Scenari di rendimento elettro-idraulico complessivo
eta_scenarios = [0.80, 0.70]

# Resa specifica annua FV ricavata dai valori stagionali citati
pv_yields = {
    'Tripoli': avg_daily_yield(SOURCES['pv_tripoli']) * 365.0,
    'Sabha': avg_daily_yield(SOURCES['pv_sabha']) * 365.0,
    'At Taj': avg_daily_yield(SOURCES['pv_taj']) * 365.0,
}

# Località scelta come base per la stima FV equivalente
base_site = 'Sabha'
base_pv_yield = pv_yields[base_site]  # kWh/kWp/anno


# ============================================================
# 4) CALCOLI PRINCIPALI
# ============================================================
results = []

for total_head_m in head_scenarios_m:
    # Il modello impone stazioni da 100 m ciascuna.
    # Number of stations = prevalenza totale / 100 m
    stations = int(round(total_head_m / 100))
    actual_total_head_m = stations * 100

    # Interasse medio tra stazioni lungo la linea geodetica
    spacing_km = L_km / stations

    # Potenza idraulica ideale totale P = rho * g * Q * H
    P_ideal_W = rho * G * Q_m3_s * actual_total_head_m

    # Potenza idraulica ideale per una singola stazione da 100 m
    P_station_ideal_W = rho * G * Q_m3_s * 100.0

    # Energia annua ideale in kWh
    E_ideal_kWh = (P_ideal_W / 1000.0) * 8760.0

    for eta in eta_scenarios:
        # Potenza elettrica reale richiesta = potenza idraulica / rendimento
        P_real_W = P_ideal_W / eta

        # Energia annua reale richiesta = energia ideale / rendimento
        E_real_kWh = E_ideal_kWh / eta

        # Potenza per stazione reale
        P_station_real_W = P_station_ideal_W / eta

        # Dimensionamento FV basato sul bilancio energetico annuo:
        # potenza FV di picco = energia annua / resa annua specifica
        pv_peak_kWp = E_real_kWh / base_pv_yield
        pv_peak_GWp = pv_peak_kWp / 1e6

        # Numero pannelli = potenza totale / potenza singolo pannello
        panel_count = (pv_peak_kWp * 1000.0) / SOURCES['panel_p_w']

        # Superficie geometrica totale moduli (senza spaziature reali di campo)
        panel_area_km2 = panel_count * SOURCES['panel_area_m2'] / 1e6

        # Lunghezza lineare se messi tutti in fila
        row_length_long_km = panel_count * SOURCES['panel_len_m'] / 1000.0
        row_length_short_km = panel_count * SOURCES['panel_wid_m'] / 1000.0

        results.append({
            'H': actual_total_head_m,
            'stations': stations,
            'spacing_km': spacing_km,
            'eta': eta,
            'P_real_GW': P_real_W / 1e9,
            'P_station_real_GW': P_station_real_W / 1e9,
            'E_real_TWh': E_real_kWh / 1e9,
            'pv_peak_GWp': pv_peak_GWp,
            'panels_million': panel_count / 1e6,
            'panel_area_km2': panel_area_km2,
            'row_length_long_km': row_length_long_km,
            'row_length_short_km': row_length_short_km,
            'pressure_per_station_bar': rho * G * 100.0 / 1e5,
        })

# Caso base usato per i commenti principali nel PDF
base = [row for row in results if row['H'] == 800 and abs(row['eta'] - 0.80) < 1e-9][0]


# ============================================================
# 5) GRAFICI
# ============================================================
# Grafico 1: potenza media annua richiesta per ogni scenario
plt.figure(figsize=(8, 4.6))
labels = [f"{row['H']} m / η={int(row['eta']*100)}%" for row in results]
values_power = [row['P_real_GW'] for row in results]
plt.bar(range(len(values_power)), values_power,
        color=['#4c78a8', '#9ecae9', '#f58518', '#ffbf79', '#54a24b', '#88d498'])
plt.xticks(range(len(values_power)), labels, rotation=25, ha='right')
plt.ylabel('Potenza elettrica media richiesta [GW]')
plt.title('Potenza media annua richiesta dal sistema di pompaggio')
plt.tight_layout()
plt.savefig('chart_power.png', dpi=180)
plt.close()

# Grafico 2: potenza FV installata necessaria per ogni scenario
plt.figure(figsize=(8, 4.6))
values_pv = [row['pv_peak_GWp'] for row in results]
plt.bar(range(len(values_pv)), values_pv,
        color=['#e45756', '#f28e8e', '#72b7b2', '#9fd0cb', '#b279a2', '#d4a6c8'])
plt.xticks(range(len(values_pv)), labels, rotation=25, ha='right')
plt.ylabel('Potenza FV installata [GWp]')
plt.title(f'Potenza fotovoltaica necessaria (base: resa annua {base_site} = {fmt(base_pv_yield,0)} kWh/kWp/anno)')
plt.tight_layout()
plt.savefig('chart_pv.png', dpi=180)
plt.close()

# Grafico 3: confronto tra rese specifiche annue usate nel modello FV
plt.figure(figsize=(8, 4.6))
site_names = list(pv_yields.keys())
site_values = [pv_yields[name] for name in site_names]
plt.bar(site_names, site_values, color=['#4c78a8', '#54a24b', '#f58518'])
plt.ylabel('Resa specifica annua [kWh/kWp/anno]')
plt.title('Resa FV annua derivata dai valori stagionali pubblicati')
plt.tight_layout()
plt.savefig('chart_yields.png', dpi=180)
plt.close()


# ============================================================
# 6) COSTRUZIONE DEL PDF
# ============================================================
outfile = 'modello_pompaggio_tripoli_sahara_analisi_accademica.pdf'
doc = SimpleDocTemplate(
    outfile,
    pagesize=A4,
    rightMargin=1.6 * cm,
    leftMargin=1.6 * cm,
    topMargin=1.6 * cm,
    bottomMargin=1.6 * cm,
)

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

story = []

# --- Front page / titolo
story.append(Paragraph(
    'Modello preliminare di pompaggio a stazioni da 100 m per il trasferimento di acqua di mare da Tripoli verso il Sahara libico',
    styles['TitleCenter']))
story.append(Paragraph(
    'Documento tecnico in stile accademico con formule, ipotesi, scenari di rendimento, modello fotovoltaico equivalente e fonti considerate',
    styles['SubTitleCenter']))
story.append(Paragraph(
    f"<b>Obiettivo.</b> Stimare l’ordine di grandezza energetico e infrastrutturale necessario a trasferire un volume d’acqua pari al doppio del Lago di Garda da Tripoli (Libia) verso il punto geografico {SOURCES['dest_coords'][0]:.6f}, {SOURCES['dest_coords'][1]:.6f} nell’arco di un anno, assumendo una catena di stazioni di pompaggio con salti nominali di 100 m.",
    styles['Justify']))

# --- Sezione 1: dati di base
story.append(Paragraph('1. Dati di base e impostazione del problema', styles['Section']))
base_data = [
    ['Parametro', 'Valore adottato', 'Nota'],
    ['Volume Lago di Garda', '49 miliardi m³', 'Valore riportato da LTER/DEIMS per il lago'],
    ['Volume da trasferire', f'{fmt(V_total_m3,0)} m³', 'Ipotesi utente: doppio del Lago di Garda'],
    ['Orizzonte temporale', '1 anno', 'Ipotesi utente'],
    ['Portata media richiesta Q', f'{fmt(Q_m3_s,2)} m³/s', 'Calcolata come V/anno'],
    ['Quota di Tripoli considerata', f'{fmt(SOURCES["tripoli_elev_m"],0)} m s.l.m.', 'Riferimento di partenza'],
    ['Distanza geodetica Tripoli-destinazione', f'{fmt(L_km,1)} km', 'Calcolata sulle coordinate, linea d’aria'],
    ['Contesto altimetrico regionale', '610–910 m', 'Plateau calcarei in Tripolitania'],
    ['Quota di Ghat (riferimento regionale)', f'{fmt(SOURCES["ghat_elev_m"],0)} m', 'Controllo di plausibilità altimetrica'],
]

tbl_base = Table(base_data, colWidths=[4.3*cm, 4.1*cm, 8.0*cm])
tbl_base.setStyle(TableStyle([
    ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#153b6b')),
    ('TEXTCOLOR', (0,0), (-1,0), colors.white),
    ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
    ('FONTSIZE', (0,0), (-1,-1), 8.8),
    ('GRID', (0,0), (-1,-1), 0.25, colors.grey),
    ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.whitesmoke, colors.HexColor('#eef3f8')]),
    ('VALIGN', (0,0), (-1,-1), 'TOP'),
]))
story.append(tbl_base)
story.append(Spacer(1, 0.3*cm))

# --- Sezione 2: formule
story.append(Paragraph('2. Formulazione matematica', styles['Section']))
for formula in [
    'Portata media annua: <b>Q = V / T</b>',
    'Potenza idraulica ideale: <b>P<sub>id</sub> = ρ · g · Q · H</b>',
    'Potenza elettrica media reale del sistema: <b>P<sub>el</sub> = P<sub>id</sub> / η</b>',
    'Energia annua reale: <b>E<sub>ann</sub> = P<sub>el</sub> · 8760 h</b>',
    'Numero stazioni da 100 m: <b>N = H / 100</b>',
    'Spaziatura media tra stazioni: <b>L<sub>st</sub> = L / N</b>',
    'Potenza di una singola stazione da 100 m: <b>P<sub>st</sub> = ρ · g · Q · 100 / η</b>',
    'Potenza fotovoltaica equivalente per coprire l’energia annua: <b>P<sub>FV,pk</sub> = E<sub>ann</sub> / Y<sub>FV</sub></b>',
    'Numero pannelli: <b>N<sub>pan</sub> = P<sub>FV,pk</sub> / P<sub>pan</sub></b>',
    'Lunghezza lineare dei pannelli in fila: <b>L<sub>fila</sub> = N<sub>pan</sub> · l<sub>pan</sub></b>',
]:
    story.append(Paragraph('• ' + formula, styles['Justify']))

# --- Sezione 3: risultati energetici
story.append(Paragraph('3. Scenari di prevalenza totale e rendimenti', styles['Section']))
story.append(Paragraph(
    'Poiché non è stata reperita una quota puntuale affidabile del punto finale nelle fonti consultate, la prevalenza totale viene modellata in tre scenari coerenti con il contesto topografico regionale: 700 m, 800 m e 900 m. Per ciascuno scenario sono considerati due rendimenti elettro-idraulici complessivi: 80% e 70%.',
    styles['Justify']))

energy_rows = [['H totale [m]', 'Stazioni', 'Interasse medio [km]', 'η', 'P media richiesta [GW]', 'P per stazione [GW]', 'E annua [TWh]']]
for row in results:
    energy_rows.append([
        str(row['H']),
        str(row['stations']),
        fmt(row['spacing_km'], 1),
        f"{int(row['eta']*100)}%",
        fmt(row['P_real_GW'], 2),
        fmt(row['P_station_real_GW'], 2),
        fmt(row['E_real_TWh'], 1),
    ])

tbl_energy = Table(energy_rows, colWidths=[2.0*cm, 1.6*cm, 2.5*cm, 1.2*cm, 3.1*cm, 3.0*cm, 2.5*cm])
tbl_energy.setStyle(TableStyle([
    ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#153b6b')),
    ('TEXTCOLOR', (0,0), (-1,0), colors.white),
    ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
    ('FONTSIZE', (0,0), (-1,-1), 8.5),
    ('GRID', (0,0), (-1,-1), 0.25, colors.grey),
    ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.whitesmoke, colors.HexColor('#eef3f8')]),
    ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
]))
story.append(tbl_energy)
story.append(Spacer(1, 0.25*cm))
story.append(Image('chart_power.png', width=16.5*cm, height=9.2*cm))
story.append(Spacer(1, 0.15*cm))

story.append(Paragraph('Lettura rapida del caso base (800 m, η = 80%)', styles['SubSection']))
story.append(Paragraph(
    f"Nel caso base, il modello richiede <b>{fmt(base['P_real_GW'],2)} GW</b> di potenza elettrica media annua. Con 8 stazioni da 100 m, l’interasse medio sarebbe pari a <b>{fmt(base['spacing_km'],1)} km</b> e ciascuna stazione richiederebbe circa <b>{fmt(base['P_station_real_GW'],2)} GW</b>. La pressione idrostatica equivalente del salto di 100 m è circa <b>{fmt(base['pressure_per_station_bar'],2)} bar</b> per stazione, senza includere ulteriori perdite distribuite e localizzate di condotta.",
    styles['Justify']))

# --- Sezione 4: fotovoltaico equivalente
story.append(PageBreak())
story.append(Paragraph('4. Modello fotovoltaico equivalente', styles['Section']))
story.append(Paragraph(
    'Per dimensionare la generazione solare, il documento usa la resa specifica annua per 1 kWp ottenuta dai valori stagionali pubblicati per Tripoli, Sabha e At Taj. La resa annua impiegata nello scenario base è quella di Sabha, interpretata come rappresentativa di una quota significativa del corridoio sahariano interno. Il modello è un bilancio energetico annuo: non dimensiona sistemi di accumulo, riserva rotante o continuità notturna.',
    styles['Justify']))

pv_rows = [['Località', 'Estate', 'Autunno', 'Inverno', 'Primavera', 'Resa annua derivata [kWh/kWp/anno]']]
for site_name, seasonals in [('Tripoli', SOURCES['pv_tripoli']), ('Sabha', SOURCES['pv_sabha']), ('At Taj', SOURCES['pv_taj'])]:
    pv_rows.append([
        site_name,
        fmt(seasonals['summer'], 2),
        fmt(seasonals['autumn'], 2),
        fmt(seasonals['winter'], 2),
        fmt(seasonals['spring'], 2),
        fmt(pv_yields[site_name], 0),
    ])

tbl_pv_yields = Table(pv_rows, colWidths=[2.2*cm, 2.0*cm, 2.0*cm, 2.0*cm, 2.2*cm, 5.2*cm])
tbl_pv_yields.setStyle(TableStyle([
    ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#153b6b')),
    ('TEXTCOLOR', (0,0), (-1,0), colors.white),
    ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
    ('FONTSIZE', (0,0), (-1,-1), 8.6),
    ('GRID', (0,0), (-1,-1), 0.25, colors.grey),
    ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.whitesmoke, colors.HexColor('#eef3f8')]),
    ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
]))
story.append(tbl_pv_yields)
story.append(Spacer(1, 0.15*cm))
story.append(Image('chart_yields.png', width=16.5*cm, height=9.2*cm))
story.append(Spacer(1, 0.15*cm))

pv_dim_rows = [['H [m]', 'η', 'FV richiesta [GWp]', 'Pannelli 550 W [milioni]', 'Superficie pannelli [km²]', 'Fila lato lungo [km]', 'Fila lato corto [km]']]
for row in results:
    pv_dim_rows.append([
        str(row['H']),
        f"{int(row['eta']*100)}%",
        fmt(row['pv_peak_GWp'], 1),
        fmt(row['panels_million'], 1),
        fmt(row['panel_area_km2'], 0),
        fmt(row['row_length_long_km'], 0),
        fmt(row['row_length_short_km'], 0),
    ])

tbl_pv = Table(pv_dim_rows, colWidths=[1.5*cm, 1.2*cm, 2.6*cm, 3.0*cm, 2.8*cm, 2.5*cm, 2.5*cm])
tbl_pv.setStyle(TableStyle([
    ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#153b6b')),
    ('TEXTCOLOR', (0,0), (-1,0), colors.white),
    ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
    ('FONTSIZE', (0,0), (-1,-1), 8.3),
    ('GRID', (0,0), (-1,-1), 0.25, colors.grey),
    ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.whitesmoke, colors.HexColor('#eef3f8')]),
    ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
]))
story.append(tbl_pv)
story.append(Spacer(1, 0.15*cm))
story.append(Image('chart_pv.png', width=16.5*cm, height=9.2*cm))
story.append(Spacer(1, 0.15*cm))

story.append(Paragraph(
    f"Nel caso base (800 m, η = 80%, resa specifica FV = {fmt(base_pv_yield,0)} kWh/kWp/anno), l’impianto richiederebbe circa <b>{fmt(base['pv_peak_GWp'],1)} GWp</b> di fotovoltaico, pari a circa <b>{fmt(base['panels_million'],1)} milioni</b> di pannelli da 550 W. Se i pannelli fossero messi in fila sul lato lungo (2,278 m), la lunghezza lineare sarebbe circa <b>{fmt(base['row_length_long_km'],0)} km</b>; sul lato corto (1,133 m), circa <b>{fmt(base['row_length_short_km'],0)} km</b>. La sola superficie geometrica dei pannelli sarebbe dell’ordine di <b>{fmt(base['panel_area_km2'],0)} km²</b>, prima di considerare spazi di servizio, interfile, viabilità, sottostazioni e accumulo.",
    styles['Justify']))

# --- Sezione 5: interpretazione ingegneristica
story.append(Paragraph('5. Interpretazione ingegneristica', styles['Section']))
for bullet in [
    'Suddividere il salto totale in stazioni da 100 m riduce la pressione per singola tratta, ma non cambia sostanzialmente l’energia teorica totale da fornire al sistema.',
    'Il modello qui sviluppato è intenzionalmente conservativo e di primo livello: non include il calcolo dettagliato delle perdite per attrito di condotte, valvole, servizi ausiliari, dissalazione o stazioni intermedie di regolazione.',
    'Il bilancio fotovoltaico è annuo. Per un’alimentazione 24/7 esclusivamente solare sarebbero necessari anche accumuli/backup e relative perdite addizionali; tale tema non è quantificato qui per non introdurre ipotesi non supportate da fonti specifiche nel presente documento.',
    'L’uso della resa di Sabha come base è una scelta metodologica trasparente: il corridoio è in buona parte interno/desertico. Il lettore può leggere la sensibilità direttamente dalla tabella delle rese di Tripoli, Sabha e At Taj.',
]:
    story.append(Paragraph('• ' + bullet, styles['Justify']))

# --- Sezione 6: conclusione sintetica
story.append(Paragraph('6. Conclusioni sintetiche', styles['Section']))
story.append(Paragraph(
    f"Per trasferire in un anno un volume pari a <b>{fmt(V_total_m3,0)} m³</b> di acqua di mare dal litorale di Tripoli verso il Sahara libico, un ordine di grandezza ragionevole per un modello a stazioni di pompaggio da 100 m è compreso tra <b>{fmt(min(r['P_real_GW'] for r in results),2)} GW</b> e <b>{fmt(max(r['P_real_GW'] for r in results),2)} GW</b> di potenza elettrica media, a seconda della prevalenza totale e del rendimento. Nel caso base di <b>800 m</b> e <b>80%</b> di rendimento, il sistema richiede circa <b>{fmt(base['P_real_GW'],2)} GW</b> medi, con una controparte fotovoltaica di circa <b>{fmt(base['pv_peak_GWp'],1)} GWp</b>. Ne emerge chiaramente che l’iniziativa è di scala infrastrutturale continentale: non un’opera puntuale, ma un sistema macro-energetico e idraulico integrato.",
    styles['Justify']))

# --- Appendici
story.append(PageBreak())
story.append(Paragraph('Appendice A — Fonti e origini considerate', styles['Section']))
source_entries = [
    ('Lago di Garda: volume 49 miliardi m³', 'LTER Italia / DEIMS-SDR', 'https://www.lteritalia.it/?page_id=458'),
    ('Lago di Garda: sito DEIMS-SDR con volume 49 miliardi m³', 'DEIMS-SDR', 'https://deims.org/c713db56-373c-46cc-8828-ce8cadc4f3bb'),
    ('Tripoli: quota puntuale 17 m', 'Maplogs', 'https://elevation.maplogs.com/poi/tripoli_libya.273406.html'),
    ('Tripoli / Tripolitania: plateau calcarei 610–910 m', 'Topographic Map / testo geografico riportato', 'https://en-us.topographic-map.com/map-s8ldb3/Tripoli/'),
    ('Tripoli District: stesso contesto geografico 610–910 m', 'Wikipedia', 'https://en.wikipedia.org/wiki/Tripoli_District,_Libya'),
    ('Ghat: quota 668 m', 'Wikipedia', 'https://en.wikipedia.org/wiki/Ghat,_Libya'),
    ('Ghat: quota 674 m', 'ElevationMap', 'https://elevationmap.net/ghat-np'),
    ('Global Solar Atlas: definizione di PVOUT e download dati per la Libia', 'World Bank / Global Solar Atlas', 'https://globalsolaratlas.info/download/libya'),
    ('Global Solar Atlas: definizione PVOUT come kWh/kWp', 'ArcGIS / Global Solar Atlas overview', 'https://www.arcgis.com/home/item.html?id=058f3cef28664e8c963d4c757f71c36d'),
    ('Studio World Bank sul potenziale fotovoltaico per Paese', 'World Bank', 'https://documents1.worldbank.org/curated/en/466331592817725242/pdf/Global-Photovoltaic-Power-Potential-by-Country.pdf'),
    ('Valori stagionali di resa FV per Tripoli, Sabha e At Taj', 'profileSOLAR', 'https://profilesolar.com/countries/LY/'),
    ('Scheda tecnica pannello 550 W: 2278 x 1133 mm', 'AE Solar datasheet', 'https://www.ae-solar.com/documents/solar_panels/Aurora/AE_MD-144_530W-550W_Ver24.1.1.pdf'),
]
for title, org, url in source_entries:
    story.append(Paragraph(f"<b>{title}</b><br/>{org}<br/><font size=8>{url}</font>", styles['Small']))
    story.append(Spacer(1, 0.06*cm))

story.append(Paragraph('Appendice B — Assunzioni dichiarate', styles['Section']))
for assumption in [
    'L’acqua di mare è trattata, in questo documento, con densità pari a 1000 kg/m³ per una stima di ordine di grandezza.',
    'La lunghezza della pipeline è una distanza geodetica in linea d’aria, non un tracciato ingegnerizzato.',
    'Le prevalenze totali sono scenari (700, 800, 900 m) coerenti con il contesto topografico regionale, non quote altimetriche definitive del tracciato.',
    'Il dimensionamento fotovoltaico è un bilancio energetico annuo; accumuli, curtailment, disponibilità, EBoP e perdite di storage non sono inclusi quantitativamente.',
]:
    story.append(Paragraph('• ' + assumption, styles['Justify']))


def add_page_num(canvas, doc_obj):
    """Footer con numerazione pagina."""
    canvas.saveState()
    canvas.setFont('Helvetica', 8)
    canvas.setFillColor(colors.grey)
    canvas.drawRightString(A4[0] - 1.6*cm, 1.0*cm, f'Pagina {doc_obj.page}')
    canvas.drawString(1.6*cm, 1.0*cm, 'Analisi preliminare — Tripoli → Sahara libico')
    canvas.restoreState()


# Build finale PDF
doc.build(story, onFirstPage=add_page_num, onLaterPages=add_page_num)

print('PDF creato:', outfile)
print('Caso base:', base)
print('Rese FV annue:', pv_yields)
