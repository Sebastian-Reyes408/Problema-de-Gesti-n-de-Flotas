import streamlit as st
import pandas as pd
import requests
import polyline
import folium
import math
from streamlit_folium import st_folium
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

# --- 1. DISEÑO Y ESTILOS EMPRESARIALES (CSS) ---
st.set_page_config(page_title="LogiRoute Pro | SRJ", layout="wide", page_icon="⚙️")

st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .stButton>button { width: 100%; border-radius: 5px; height: 3em; background-color: #0044ff; color: white; }
    .stMetric { background-color: #ffffff; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    [data-testid="stSidebar"] { background-color: #1e293b; color: white; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. LOGICA DE CONEXIÓN A MAPAS (OSRM) ---
def get_osrm_matrix(df):
    coords = ";".join([f"{row.lon},{row.lat}" for _, row in df.iterrows()])
    url = f"http://router.project-osrm.org/table/v1/driving/{coords}?annotations=distance"
    try:
        r = requests.get(url, timeout=10)
        return [[int(d) for d in row] for row in r.json()['distances']]
    except: return None

def get_osrm_route(p1, p2):
    url = f"http://router.project-osrm.org/route/v1/driving/{p1[1]},{p1[0]};{p2[1]},{p2[0]}?overview=full"
    try:
        r = requests.get(url, timeout=5)
        return polyline.decode(r.json()['routes'][0]['geometry'])
    except: return []

# --- 3. GESTIÓN DE DATOS ---
if 'df_master' not in st.session_state:
    st.session_state.df_master = pd.DataFrame({
        "ID": ["DEPOT", "Norte 1", "Manga 2", "Bocagrande 3", "Crespo 4", "Mamonal 5"],
        "lat": [10.4246, 10.4480, 10.4180, 10.4000, 10.4500, 10.3150],
        "lon": [-75.5262, -75.5150, -75.5350, -75.5500, -75.5000, -75.4980],
        "Demanda": [0, 200, 150, 400, 300, 600]
    })

# --- 4. INTERFAZ: BARRA LATERAL ---
with st.sidebar:
    st.title("⚙️ LogiRoute SRJ")
    st.markdown("---")
    st.subheader("📁 Carga de datos")
    uploaded_file = st.file_uploader("Subir Excel o CSV", type=["xlsx", "csv"])
    if uploaded_file:
        st.session_state.df_master = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
        st.success("Archivo cargado!")

    st.subheader("🚛 Configuración de Flota")
    n_veh = st.number_input("Vehículos Disponibles", 1, 10, 3)
    cap_veh = st.number_input("Capacidad por Camión", 100, 5000, 1200)
    
    st.subheader("🧠 Motor de Cálculo")
    t_limit = st.slider("Precisión (Segundos)", 2, 60, 5)

# --- 5. INTERFAZ: CUERPO PRINCIPAL ---
tab1, tab2 = st.tabs(["📊 Planificación y Datos", "🗺️ Mapa de Operaciones"])

with tab1:
    col_t1, col_t2 = st.columns([2, 1])
    with col_t1:
        st.subheader("📦 Editor de Demanda Diaria")
        df_final = st.data_editor(st.session_state.df_master, num_rows="dynamic", use_container_width=True, key="editor")
    with col_t2:
        st.subheader("📈 Resumen de Carga")
        total_d = df_final['Demanda'].sum()
        st.metric("Volumen Total", f"{total_d} unds")
        st.metric("Capacidad Total Flota", f"{n_veh * cap_veh} unds")
        if total_d > (n_veh * cap_veh):
            st.error("⚠️ Alerta: Demanda excede capacidad.")

with tab2:
    m = folium.Map(location=[df_final.lat.mean(), df_final.lon.mean()], zoom_start=12, tiles="cartodbpositron")
    colors = ['blue', 'red', 'green', 'orange', 'purple', 'black']
    
    if st.button("🚀 OPTIMIZAR RUTAS CARRETEABLES", use_container_width=True):
        matrix = get_osrm_matrix(df_final)
        if matrix:
            # --- OR-Tools Core ---
            manager = pywrapcp.RoutingIndexManager(len(matrix), n_veh, 0)
            routing = pywrapcp.RoutingModel(manager)
            def d_cb(f, t): return matrix[manager.IndexToNode(f)][manager.IndexToNode(t)]
            routing.SetArcCostEvaluatorOfAllVehicles(routing.RegisterTransitCallback(d_cb))
            def q_cb(f): return df_final['Demanda'].tolist()[manager.IndexToNode(f)]
            routing.AddDimensionWithVehicleCapacity(routing.RegisterUnaryTransitCallback(q_cb), 0, [cap_veh]*n_veh, True, 'Capacity')
            
            search_p = pywrapcp.DefaultRoutingSearchParameters()
            search_p.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
            search_p.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
            search_p.time_limit.FromSeconds(t_limit)
            
            solution = routing.SolveWithParameters(search_p)
            
            if solution:
                st.success("✅ Solución Óptima Encontrada")
                results_list = []
                res_vehiculos = [] # Para guardar el resumen de km por camión
                distancia_total_flota = 0
                
                for v_id in range(n_veh):
                    idx = routing.Start(v_id)
                    step = 0
                    color = colors[v_id % len(colors)]
                    distancia_vehiculo_m = 0 # Variable para sumar los metros recorridos
                    
                    while not routing.IsEnd(idx):
                        node = manager.IndexToNode(idx)
                        p_curr = df_final.iloc[node]
                        results_list.append({"Vehículo": v_id+1, "Parada": step, "ID": p_curr.ID, "Carga": p_curr.Demanda})
                        
                        # Marcador
                        folium.Marker([p_curr.lat, p_curr.lon], popup=f"V{v_id+1} S{step}", 
                                      icon=folium.Icon(color=color, icon='info-sign')).add_to(m)
                        
                        # Avanzar al siguiente nodo
                        prev_idx = idx
                        idx = solution.Value(routing.NextVar(idx))
                        
                        # --- EXTRACCIÓN DE DISTANCIA ---
                        # Le preguntamos al motor de OR-Tools cuánto costó (en metros) este tramo exacto
                        distancia_vehiculo_m += routing.GetArcCostForVehicle(prev_idx, idx, v_id)
                        
                        # Trazado de calles
                        next_p = df_final.iloc[manager.IndexToNode(idx)]
                        path = get_osrm_route([p_curr.lat, p_curr.lon], [next_p.lat, next_p.lon])
                        if path: folium.PolyLine(path, color=color, weight=5, opacity=0.7).add_to(m)
                        step += 1
                        
                    # Convertir los metros de OSRM a Kilómetros para mejor lectura
                    distancia_km = distancia_vehiculo_m / 1000.0
                    distancia_total_flota += distancia_km
                    res_vehiculos.append({"v_id": v_id+1, "dist_km": distancia_km})
                
                # Mostrar Mapa
                st_folium(m, width="100%", height=500, returned_objects=[])
                
                # --- NUEVA SECCIÓN DE RESULTADOS CON MÉTRICAS ---
                st.divider()
                st.subheader("📊 KPIs Globales de la Operación")
                
                # Contamos cuántos camiones realmente salieron del almacén
                res_df = pd.DataFrame(results_list)
                # Contamos solo los vehículos que entregaron carga a clientes reales
                camiones_con_carga = res_df[res_df['Carga'] > 0]
                camiones_activos = camiones_con_carga['Vehículo'].nunique()
                
                col_kpi1, col_kpi2, col_kpi3 = st.columns(3)
                col_kpi1.metric("Distancia Total Flota", f"{distancia_total_flota:.2f} km")
                col_kpi2.metric("Vehículos Despachados", f"{camiones_activos} de {n_veh}")
                col_kpi3.metric("Carga Total Entregada", f"{res_df['Carga'].sum()} unds")

                st.subheader("📥 Plan de Despacho Detallado")
                
                # --- MENÚS DESPLEGABLES ENRIQUECIDOS ---
                for v_summary in res_vehiculos:
                    v_id_real = v_summary["v_id"]
                    dist_km = v_summary["dist_km"]
                    datos_vehiculo = res_df[res_df['Vehículo'] == v_id_real]
                    
                    # Solo mostramos el menú si el camión realmente entregó carga
                    if datos_vehiculo['Carga'].sum() > 0:
                        with st.expander(f"🚚 Hoja de Ruta: Vehículo {v_id_real} | Recorrido: {dist_km:.2f} km"):
                            col_tabla, col_stats = st.columns([2, 1])
                            
                            with col_tabla:
                                st.markdown("**Secuencia de Visitas:**")
                                st.dataframe(datos_vehiculo[['Parada', 'ID', 'Carga']], use_container_width=True)
                            
                            with col_stats:
                                st.markdown("**Métricas de la Ruta:**")
                                carga_total_v = datos_vehiculo['Carga'].sum()
                                utilizacion = (carga_total_v / cap_veh) * 100
                                
                                st.metric("Distancia del Viaje", f"{dist_km:.2f} km")
                                st.metric("Carga Total Asignada", f"{carga_total_v} unds")
                                
                                fraccion_progreso = min(carga_total_v / cap_veh, 1.0)
                                st.progress(fraccion_progreso, text=f"{utilizacion:.1f}% de capacidad")
                                
                                if utilizacion < 50:
                                    st.warning("⚠️ Ocupación ineficiente (< 50%)")
                                    
                # Botón de exportación actualizado (Corregido para Excel en Español)
                csv = res_df.to_csv(index=False, sep=';').encode('utf-8-sig')
                st.download_button("Descargar Plan Maestro (CSV)", csv, "rutas_completas.csv", "text/csv")