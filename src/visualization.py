import logging
import pandas as pd
import numpy as np
import folium
import plotly.express as px
import plotly.graph_objects as go
import networkx as nx
import matplotlib.pyplot as plt
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

def plot_od_matrix_heatmap(df: pd.DataFrame, value_col: str = "duration_traffic_s", title: str = None) -> go.Figure:
    """
    Generates a Plotly heatmap of the Origin-Destination matrix.
    """
    if df.empty:
        logger.warning("Dataframe is empty. Cannot plot OD heatmap.")
        return go.Figure()

    # Pivot dataframe to get matrix form
    pivot_df = df.pivot(index="origin_id", columns="destination_id", values=value_col)
    
    # Order: hub first, then stores
    all_nodes = list(pivot_df.index)
    sorted_nodes = sorted(all_nodes, key=lambda n: 0 if n == "hub" else 1)
    pivot_df = pivot_df.reindex(index=sorted_nodes, columns=sorted_nodes)

    if value_col == "duration_traffic_s":
        # Convert seconds to minutes for readability
        pivot_df = pivot_df / 60.0
        z_label = "Duração (minutos)"
        colorscale = "Viridis"
    elif value_col == "distance_m":
        pivot_df = pivot_df / 1000.0
        z_label = "Distância (km)"
        colorscale = "Plasma"
    elif value_col == "traffic_ratio":
        z_label = "Traffic Ratio"
        colorscale = "RdBu_r" # Blue para menor (1.0) e Red para maior
    else:
        z_label = value_col
        colorscale = "RdBu_r"

    if not title:
        title = f"Matriz Origem-Destino - {z_label}"

    fig = px.imshow(
        pivot_df,
        labels=dict(x="Destino", y="Origem", color=z_label),
        x=pivot_df.columns,
        y=pivot_df.index,
        color_continuous_scale=colorscale,
        text_auto=".1f",  # show values inside matrix cells
        title=title
    )
    fig.update_layout(
        xaxis_title="Destino",
        yaxis_title="Origem",
        width=800,
        height=700,
        title_x=0.5
    )
    return fig

def plot_temporal_heatmap(df: pd.DataFrame, origin_id: str, destination_id: str, value_col: str = "duration_traffic_s") -> go.Figure:
    """
    Plots a heatmap showing hourly variations (X-axis) across days of the week (Y-axis)
    for a specific Origin-Destination pair.
    """
    if df.empty:
        return go.Figure()

    # Filter for the specific O-D pair
    pair_df = df[(df["origin_id"] == origin_id) & (df["destination_id"] == destination_id)].copy()
    if pair_df.empty:
        logger.warning(f"No records found for pair: {origin_id} -> {destination_id}")
        return go.Figure()

    # If datetime is not parsed, extract day of week and hour
    if "day_name" not in pair_df.columns or "hour" not in pair_df.columns:
        dt = pd.to_datetime(pair_df["timestamp"])
        pair_df["day_name"] = dt.dt.strftime("%A")
        pair_df["hour"] = dt.dt.hour

    # Convert seconds to minutes if duration
    if value_col == "duration_traffic_s":
        pair_df["val"] = pair_df[value_col] / 60.0
        z_label = "Tempo de Trajeto (min)"
    else:
        pair_df["val"] = pair_df[value_col]
        z_label = value_col

    # Group and pivot
    grouped = pair_df.groupby(["day_name", "hour"])["val"].mean().reset_index()
    
    # Order days logically
    day_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    pivot_df = grouped.pivot(index="day_name", columns="hour", values="val")
    pivot_df = pivot_df.reindex(day_order)

    fig = px.imshow(
        pivot_df,
        labels=dict(x="Hora do Dia", y="Dia da Semana", color=z_label),
        x=pivot_df.columns,
        y=pivot_df.index,
        color_continuous_scale="Thermal",
        text_auto=".1f",
        title=f"Variação Temporal: {origin_id} → {destination_id}"
    )
    fig.update_layout(
        xaxis=dict(tickmode="linear", tick0=0, dtick=1),
        xaxis_title="Hora do Dia",
        yaxis_title="Dia da Semana",
        width=900,
        height=500,
        title_x=0.5
    )
    return fig

def plot_network_graph(locations: List[Dict[str, Any]], records: List[Dict[str, Any]], value_col: str = "duration_traffic_s") -> plt.Figure:
    """
    Plots a geographic graph using NetworkX.
    Nodes are located at their real lat/lng coordinates.
    Edges are color-coded based on travel time.
    """
    G = nx.DiGraph()

    # Add nodes
    pos = {}
    node_colors = []
    for loc in locations:
        node_id = loc["id"]
        G.add_node(node_id, name=loc["name"], type=loc["type"])
        pos[node_id] = (loc["lng"], loc["lat"])  # X=lng, Y=lat for geolayout
        if loc["type"] == "hub":
            node_colors.append("red")
        else:
            node_colors.append("dodgerblue")

    # Add edges
    edge_weights = []
    for rec in records:
        o_id = rec["origin_id"]
        d_id = rec["destination_id"]
        if o_id != d_id:  # skip self loops
            val = rec[value_col]
            if value_col == "duration_traffic_s":
                val = val / 60.0  # seconds to minutes
            G.add_edge(o_id, d_id, weight=val)
            edge_weights.append(val)

    # Plotting setup
    fig, ax = plt.subplots(figsize=(10, 8), dpi=100)
    
    # Draw nodes
    nx.draw_networkx_nodes(
        G, pos, 
        node_color=node_colors, 
        node_size=[500 if G.nodes[n]["type"] == "hub" else 250 for n in G.nodes],
        alpha=0.9, 
        ax=ax
    )
    
    # Draw labels (small offsets so they don't cover nodes)
    label_pos = {k: (v[0] + 0.003, v[1] + 0.003) for k, v in pos.items()}
    labels = {n: G.nodes[n]["name"] for n in G.nodes}
    nx.draw_networkx_labels(G, label_pos, labels=labels, font_size=8, font_weight="bold", ax=ax)

    # Normalize edges for color mapping
    if edge_weights:
        min_w, max_w = min(edge_weights), max(edge_weights)
        norm_weights = [0.1 + 2.0 * (w - min_w) / (max_w - min_w + 1e-5) for w in edge_weights]
    else:
        norm_weights = 1.0

    # Draw edges
    edges = nx.draw_networkx_edges(
        G, pos,
        width=norm_weights,
        edge_color=edge_weights,
        edge_cmap=plt.cm.plasma,
        arrowsize=10,
        alpha=0.6,
        ax=ax
    )

    # Colorbar
    if edge_weights:
        sm = plt.cm.ScalarMappable(cmap=plt.cm.plasma, norm=plt.Normalize(vmin=min(edge_weights), vmax=max(edge_weights)))
        sm.set_array([])
        cbar = fig.colorbar(sm, ax=ax, label="Tempo de Trajeto (minutos)" if value_col == "duration_traffic_s" else value_col)

    ax.set_title("Grafo Dirigido da Rede de Entregas (Posições Geográficas)")
    ax.axis("off")
    plt.tight_layout()
    return fig

def plot_interactive_routes_map(locations: List[Dict[str, Any]], polylines_geojson: Optional[List[Dict[str, Any]]] = None) -> folium.Map:
    """
    Creates an interactive folium map plotting the 15 points.
    If polylines_geojson is provided, draws actual routes on the map.
    """
    # Find hub for centering
    hub_loc = next((loc for loc in locations if loc["type"] == "hub"), locations[0])
    mapa = folium.Map(location=[hub_loc["lat"], hub_loc["lng"]], zoom_start=12, tiles="cartodbpositron")

    # Add location markers
    for loc in locations:
        is_hub = loc["type"] == "hub"
        color = "red" if is_hub else "blue"
        icon_name = "home" if is_hub else "shopping-cart"
        
        popup_html = f"""
        <div style='font-family: Arial, sans-serif; min-width: 200px;'>
            <h4 style='margin: 0 0 5px 0;'>{loc['name']}</h4>
            <p style='margin: 0;'><b>ID:</b> {loc['id']}</p>
            <p style='margin: 0;'><b>Endereço:</b> {loc['address']}</p>
        </div>
        """
        folium.Marker(
            location=[loc["lat"], loc["lng"]],
            popup=folium.Popup(popup_html, max_width=300),
            tooltip=f"{'Hub' if is_hub else 'Loja'}: {loc['name']}",
            icon=folium.Icon(color=color, icon=icon_name, prefix="fa")
        ).add_to(mapa)

    # Draw Polylines (if provided)
    if polylines_geojson:
        if isinstance(polylines_geojson, dict) and polylines_geojson.get("type") == "FeatureCollection":
            routes_list = polylines_geojson.get("features", [])
        elif isinstance(polylines_geojson, list):
            routes_list = polylines_geojson
        else:
            routes_list = []

        for route in routes_list:
            if not isinstance(route, dict):
                continue

            # Check if it is a GeoJSON Feature
            if route.get("type") == "Feature":
                props = route.get("properties", {})
                geojson_geom = route.get("geometry")
                o_id = props.get("origin_id")
                d_id = props.get("destination_id")
                duration_s = props.get("duration_s", 0)
                distance_m = props.get("distance_m", 0)
            else:
                o_id = route.get("origin_id")
                d_id = route.get("destination_id")
                duration_s = route.get("duration_s", 0)
                distance_m = route.get("distance_m", 0)
                geojson_geom = route.get("geojson")
                if not geojson_geom and route.get("coordinates"):
                    geojson_geom = {
                        "type": "LineString",
                        "coordinates": [[lng, lat] for lat, lng in route["coordinates"]]
                    }

            if not geojson_geom or not o_id or not d_id:
                continue

            dur_min = duration_s / 60.0
            dist_km = distance_m / 1000.0
            
            # Simple color coding for duration
            if dur_min < 15:
                color = "green"
            elif dur_min < 30:
                color = "orange"
            else:
                color = "red"

            tooltip_txt = f"{o_id} → {d_id} | {dur_min:.1f} min | {dist_km:.1f} km"
            
            # Draw line
            folium.GeoJson(
                geojson_geom,
                style_function=lambda x, col=color: {
                    "color": col,
                    "weight": 2.5,
                    "opacity": 0.5
                },
                tooltip=tooltip_txt
            ).add_to(mapa)

    return mapa
