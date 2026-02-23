'use client';

import { useCallback, useState } from 'react';
import { Upload, FileType, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { projectsApi } from '@/lib/api';
import { wsManager } from '@/lib/websocket';
import { useAppStore } from '@/store/useAppStore';
import type { PlotInfo } from '@/types/api';

interface PlotUploadProps {
  projectId: string;
  onAnalysed: (plot: PlotInfo) => void;
}

export function PlotUpload({ projectId, onAnalysed }: PlotUploadProps) {
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [status, setStatus] = useState('');
  const { accessToken } = useAppStore();

  async function handleFile(file: File) {
    if (!file.name.match(/\.(dwg|dxf)$/i)) {
      toast.error('Please upload a DWG or DXF file');
      return;
    }
    setUploading(true);
    setStatus('Getting upload URL…');

    try {
      const { upload_url, key } = await projectsApi.getPlotUploadUrl(projectId);

      setStatus('Uploading file…');
      await fetch(upload_url, {
        method: 'PUT',
        body: file,
        headers: { 'Content-Type': 'application/octet-stream' },
      });

      setStatus('Analysing plot…');
      await projectsApi.submitPlot(projectId, { storage_key: key, filename: file.name });

      // Listen for plot.analysed WebSocket event
      if (accessToken) {
        wsManager.connect(projectId, accessToken);
        const unsubscribe = wsManager.on('plot.analysed', (data) => {
          unsubscribe();
          wsManager.disconnect();
          onAnalysed(data as PlotInfo);
          setUploading(false);
        });

        wsManager.on('error', () => {
          unsubscribe();
          wsManager.disconnect();
          toast.error('Connection error during plot analysis');
          setUploading(false);
        });
      }
    } catch {
      toast.error('Upload failed. Please try again.');
      setUploading(false);
    }
  }

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  }, [projectId, accessToken]);

  const onInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
  };

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
      className={`border-2 border-dashed rounded-xl p-12 text-center transition-colors ${
        dragging ? 'border-blue-400 bg-blue-50' : 'border-gray-300 bg-white hover:border-gray-400'
      }`}
    >
      {uploading ? (
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="w-10 h-10 text-blue-500 animate-spin" />
          <p className="text-sm font-medium text-gray-700">{status}</p>
          <p className="text-xs text-gray-400">This may take a moment…</p>
        </div>
      ) : (
        <label className="cursor-pointer flex flex-col items-center gap-4">
          <div className="w-16 h-16 bg-blue-50 rounded-2xl flex items-center justify-center">
            {dragging ? (
              <FileType className="w-8 h-8 text-blue-500" />
            ) : (
              <Upload className="w-8 h-8 text-blue-400" />
            )}
          </div>
          <div>
            <p className="font-semibold text-gray-800 text-sm">
              {dragging ? 'Drop your file here' : 'Drop DWG/DXF file here'}
            </p>
            <p className="text-gray-400 text-xs mt-1">or click to browse</p>
          </div>
          <p className="text-xs text-gray-400">Supports .dwg and .dxf files</p>
          <input
            type="file"
            accept=".dwg,.dxf"
            className="hidden"
            onChange={onInputChange}
          />
        </label>
      )}
    </div>
  );
}
