import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from common import CHART_COLORS, CARGO_COLORS


def yoy_bar_chart(df: pd.DataFrame, x: str, y: str, title: str):
    """Bar chart of `y` by `x` with a YoY/MoM % change line on a secondary axis."""
    df = df.sort_values(x).reset_index(drop=True)
    pct = df[y].pct_change() * 100

    fig = go.Figure()
    fig.add_bar(x=df[x], y=df[y], name=y, marker_color=CHART_COLORS[0])
    fig.add_trace(go.Scatter(x=df[x], y=pct, name="% change", yaxis="y2", mode="lines+markers", line=dict(color=CHART_COLORS[1])))
    fig.update_layout(
        title=title,
        yaxis=dict(title=y),
        yaxis2=dict(title="% change", overlaying="y", side="right", showgrid=False),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(t=60),
    )
    return fig


def simple_forecast_chart(df: pd.DataFrame, x: str, y: str, periods: int, title: str):
    """Linear-trend extrapolation — a simple projection, not a statistical forecast."""
    df = df.sort_values(x).reset_index(drop=True)
    xs = df[x].astype(float).values
    ys = df[y].astype(float).values
    if len(xs) < 2:
        fig = go.Figure()
        fig.update_layout(title=f"{title} (not enough data)")
        return fig

    coeffs = np.polyfit(xs, ys, 1)
    future_x = np.array([xs[-1] + i for i in range(1, periods + 1)])
    future_y = np.polyval(coeffs, future_x)

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines+markers", name="Actual", line=dict(color=CHART_COLORS[0])))
    fig.add_trace(go.Scatter(
        x=np.concatenate([[xs[-1]], future_x]),
        y=np.concatenate([[ys[-1]], future_y]),
        mode="lines+markers", name="Projection (linear trend)",
        line=dict(color=CHART_COLORS[1], dash="dash"),
    ))
    fig.update_layout(title=title, margin=dict(t=60))
    return fig


def donut_chart(df: pd.DataFrame, names: str, values: str, title: str, top_n: int = 10):
    df = df.sort_values(values, ascending=False).head(top_n)
    fig = px.pie(df, names=names, values=values, title=title, hole=0.55, color_discrete_sequence=CHART_COLORS)
    fig.update_traces(textinfo="percent+label")
    return fig


def hbar_chart(df: pd.DataFrame, y: str, x: str, title: str, top_n: int = 20, color=None):
    df = df.sort_values(x, ascending=False).head(top_n).sort_values(x)
    fig = px.bar(df, x=x, y=y, orientation="h", title=title, color_discrete_sequence=[color or CHART_COLORS[0]])
    return fig


def treemap_chart(df: pd.DataFrame, path: list, values: str, title: str, color: str | None = None):
    fig = px.treemap(
        df, path=path, values=values, title=title,
        color=color or path[0], color_discrete_sequence=CHART_COLORS,
    )
    return fig


def sankey_chart(df: pd.DataFrame, source_col: str, target_col: str, value_col: str, title: str, top_n: int = 20):
    df = df.sort_values(value_col, ascending=False).head(top_n)
    sources = df[source_col].astype(str) + " (load)"
    targets = df[target_col].astype(str) + " (discharge)"
    labels = list(pd.unique(pd.concat([sources, targets])))
    idx = {label: i for i, label in enumerate(labels)}

    fig = go.Figure(go.Sankey(
        node=dict(label=labels, color=CHART_COLORS[0]),
        link=dict(
            source=[idx[s] for s in sources],
            target=[idx[t] for t in targets],
            value=df[value_col].tolist(),
            color="rgba(27,108,168,0.3)",
        ),
    ))
    fig.update_layout(title=title, margin=dict(t=60))
    return fig


def cargo_color_map(series):
    return [CARGO_COLORS.get(v, CHART_COLORS[-1]) for v in series]
