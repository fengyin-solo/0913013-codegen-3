import React from 'react';
import { useSelector } from 'react-redux';
import * as THREE from 'three';
import { RootState } from '../store';

const MeasurementOverlay: React.FC = () => {
  const measurementPoints = useSelector((state: RootState) => state.viewer.measurementPoints);
  const lastMeasurement = useSelector((state: RootState) => state.viewer.lastMeasurement);
  const tool = useSelector((state: RootState) => state.viewer.tool);

  const pointsGeometry = React.useMemo(() => {
    const positions = new Float32Array(measurementPoints.length * 3);
    measurementPoints.forEach((p, i) => {
      positions[i * 3] = p.x;
      positions[i * 3 + 1] = p.y;
      positions[i * 3 + 2] = p.z;
    });
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    return geometry;
  }, [measurementPoints]);

  const lineGeometry = React.useMemo(() => {
    if (measurementPoints.length < 2) return null;
    const positions = new Float32Array(measurementPoints.length * 3);
    measurementPoints.forEach((p, i) => {
      positions[i * 3] = p.x;
      positions[i * 3 + 1] = p.y;
      positions[i * 3 + 2] = p.z;
    });
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    return geometry;
  }, [measurementPoints]);

  if (tool !== 'measure') return null;

  return (
    <group>
      {measurementPoints.map((point, index) => (
        <mesh key={index} position={[point.x, point.y, point.z]}>
          <sphereGeometry args={[2, 16, 16]} />
          <meshBasicMaterial color="#ff4d4f" />
        </mesh>
      ))}

      {lineGeometry && (
        <lineSegments geometry={lineGeometry}>
          <lineBasicMaterial color="#ff4d4f" linewidth={2} />
        </lineSegments>
      )}

      {measurementPoints.length > 0 && (
        <sprite position={[
          measurementPoints[measurementPoints.length - 1].x,
          measurementPoints[measurementPoints.length - 1].y + 5,
          measurementPoints[measurementPoints.length - 1].z
        ]}>
          <spriteMaterial>
            <canvasTexture
              image={(function createLabel() {
                const canvas = document.createElement('canvas');
                canvas.width = 128;
                canvas.height = 32;
                const ctx = canvas.getContext('2d')!;
                ctx.fillStyle = 'rgba(0, 0, 0, 0.7)';
                ctx.fillRect(0, 0, 128, 32);
                ctx.fillStyle = '#ffffff';
                ctx.font = '12px Arial';
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                if (lastMeasurement && measurementPoints.length >= 2) {
                  ctx.fillText(`${lastMeasurement.value.toFixed(2)} ${lastMeasurement.unit}`, 64, 16);
                } else {
                  ctx.fillText(`点 ${measurementPoints.length}`, 64, 16);
                }
                return canvas;
              })()}
            />
          </spriteMaterial>
        </sprite>
      )}
    </group>
  );
};

export default MeasurementOverlay;
