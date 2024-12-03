from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import json
import os

app = FastAPI(title="Building Presence Change Analysis API")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins. Restrict to specific origins in production.
    allow_credentials=True,
    allow_methods=["*"],  # Allows all HTTP methods
    allow_headers=["*"],  # Allows all headers
)

# Preloaded file paths for SRM, Jindal, and Sec46
PRELOADED_FILES = {
    "SRM": {
        "2023": "Hexagon 2000/construction_points_SRM_new_23.csv",
        "2021": "Hexagon 2000/construction_points_SRM_new_20.csv"
    },
    "Jindal": {
        "2023": "Hexagon 2000/construction_points_Jindal_23.csv",
        "2021": "Hexagon 2000/construction_points_Jindal_20.csv"
    },
    "Sec46": {
        "2023": "Hexagon 2000/construction_points_sec46_23.csv",
        "2021": "Hexagon 2000/construction_points_sec46_20.csv"
    }
}

# Output paths
OUTPUT_PATHS = {
    "visualizations": "outputs/visualizations/",
    "geojson": "outputs/geojson/"
}


def load_and_prepare_data(dataset_type: str):
    """
    Load datasets for the specified dataset type (SRM, Jindal, or Sec46).
    """
    if dataset_type not in PRELOADED_FILES:
        raise ValueError(f"Dataset type '{dataset_type}' is not recognized. Use 'SRM', 'Jindal', or 'Sec46'.")

    # Load data for 2021 and 2023
    data_2021_path = PRELOADED_FILES[dataset_type]["2021"]
    data_2023_path = PRELOADED_FILES[dataset_type]["2023"]

    df1 = pd.read_csv(data_2021_path)
    df2 = pd.read_csv(data_2023_path)

    # Add year identifier
    df1['dataset'] = '2021'
    df2['dataset'] = '2023'

    return df1, df2


def detect_presence_changes(df1, df2):
    """
    Detect and analyze changes in building presence between the two datasets.
    """
    # Merge datasets on coordinates, including .geo column
    merged_df = pd.merge(
        df1[['latitude', 'longitude', 'presence', 'dataset', '.geo']],
        df2[['latitude', 'longitude', 'presence', 'dataset', '.geo']],
        on=['latitude', 'longitude'],
        suffixes=('_2021', '_2023')
    )

    # Calculate changes (1 if presence changed, 0 if remained same)
    merged_df['presence_change'] = (merged_df['presence_2023'] != merged_df['presence_2021']).astype(int)

    # Identify locations with changes
    changes = merged_df[merged_df['presence_change'] == 1]

    return merged_df, changes


def create_geojson(changes_df, dataset_type):
    """
    Convert the changes to GeoJSON format.
    """
    features = []

    for idx, row in changes_df.iterrows():
        feature = {
            "type": "Feature",
            "properties": {
                "change_type": "new" if row['presence_2023'] > row['presence_2021'] else "removed",
                "year_2021": int(row['presence_2021']),
                "year_2023": int(row['presence_2023']),
                "geo": row['.geo_2023'] if pd.notna(row['.geo_2023']) else row['.geo_2021']
            },
            "geometry": {
                "type": "Point",
                "coordinates": [float(row['longitude']), float(row['latitude'])]
            }
        }
        features.append(feature)

    geojson = {
        "type": "FeatureCollection",
        "features": features
    }

    # Save GeoJSON to file
    geojson_path = f"{OUTPUT_PATHS['geojson']}building_changes_{dataset_type}.geojson"
    with open(geojson_path, 'w') as f:
        json.dump(geojson, f)

    return geojson


def visualize_changes(merged_df, changes, dataset_type):
    """
    Create visualizations of the presence changes.
    """
    plt.figure(figsize=(12, 8))

    # Plot all points
    plt.scatter(merged_df['longitude'], merged_df['latitude'],
                c='blue', alpha=0.3, label='No Change')

    # Highlight changes
    if len(changes) > 0:
        plt.scatter(changes['longitude'],
                    changes['latitude'],
                    c='red', marker='x', s=100, label='Changed')

    plt.xlabel('Longitude')
    plt.ylabel('Latitude')
    plt.title(f'Spatial Distribution of Building Presence Changes ({dataset_type})')
    plt.legend()

    # Save plot with a unique filename
    output_filename = f"{OUTPUT_PATHS['visualizations']}building_changes_visualization_{dataset_type}.png"
    plt.savefig(output_filename)
    plt.close()

    return output_filename


@app.get("/analyze-building-changes/")
async def analyze_building_changes(dataset_type: str = Query(..., description="Dataset type: SRM, Jindal, or Sec46")):
    """
    Analyze building presence changes for the given dataset type (SRM, Jindal, or Sec46).
    """
    try:
        # Load and prepare data
        df1, df2 = load_and_prepare_data(dataset_type)

        # Detect changes
        merged_df, changes = detect_presence_changes(df1, df2)

        # Prepare summary
        summary = {
            'total_points': len(merged_df),
            'total_changes': len(changes),
            'change_percentage': (len(changes) / len(merged_df) * 100),
            'new_buildings': len(changes[changes['presence_2023'] > changes['presence_2021']]),
            'removed_buildings': len(changes[changes['presence_2023'] < changes['presence_2021']])
        }

        # Create GeoJSON
        geojson = create_geojson(changes, dataset_type)

        # Create visualization
        visualization_path = visualize_changes(merged_df, changes, dataset_type)

        return {
            "summary": summary,
            "geojson": geojson,
            "visualization_path": visualization_path,
            "changes": changes.to_dict(orient="records")
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/visualization/")
async def get_visualization(dataset_type: str = Query(..., description="Dataset type: SRM, Jindal, or Sec46")):
    """
    Retrieve the last generated visualization for the given dataset type.
    """
    visualization_path = f"{OUTPUT_PATHS['visualizations']}building_changes_visualization_{dataset_type}.png"

    if not os.path.exists(visualization_path):
        raise HTTPException(status_code=404, detail=f"No visualization found for dataset type '{dataset_type}'.")

    return FileResponse(visualization_path, media_type="image/png")


@app.get("/geojson/")
async def get_geojson(dataset_type: str = Query(..., description="Dataset type: SRM, Jindal, or Sec46")):
    """
    Retrieve the last generated GeoJSON for the given dataset type.
    """
    geojson_path = f"{OUTPUT_PATHS['geojson']}building_changes_{dataset_type}.geojson"

    if not os.path.exists(geojson_path):
        raise HTTPException(status_code=404, detail=f"No GeoJSON found for dataset type '{dataset_type}'.")

    with open(geojson_path, 'r') as f:
        geojson_data = json.load(f)

    return geojson_data


@app.get("/health")
async def health_check():
    """
    Simple health check endpoint.
    """
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
