'use client';

import { useState } from 'react';
import { Upload, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { adminApi } from '@/lib/api';
import { useQueryClient } from '@tanstack/react-query';

export function BuildingCodeUpload() {
  const [open, setOpen] = useState(false);
  const [jurisdiction, setJurisdiction] = useState('NP-KTM');
  const [uploading, setUploading] = useState(false);
  const qc = useQueryClient();

  async function handleFile(file: File) {
    if (!file.name.endsWith('.pdf')) { toast.error('Please upload a PDF file'); return; }
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('jurisdiction', jurisdiction);
      fd.append('title', file.name.replace('.pdf', ''));
      await adminApi.uploadBuildingCode(fd);
      toast.success('PDF uploaded. Extraction job started.');
      qc.invalidateQueries({ queryKey: ['building-codes'] });
      setOpen(false);
    } catch { toast.error('Upload failed'); } finally { setUploading(false); }
  }

  return (
    <>
      <button onClick={() => setOpen(true)} className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700">
        <Upload className="w-4 h-4" /> Upload PDF
      </button>

      {open && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl p-6 w-full max-w-md shadow-2xl">
            <h2 className="font-semibold text-gray-900 mb-4">Upload Building Code PDF</h2>
            <div className="mb-4">
              <label className="block text-xs font-medium text-gray-600 mb-1">Jurisdiction</label>
              <select value={jurisdiction} onChange={(e) => setJurisdiction(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                <option value="NP-KTM">Nepal — Kathmandu</option>
                <option value="NP-PKR">Nepal — Pokhara</option>
                <option value="IN-MH">India — Maharashtra</option>
                <option value="US-CA">USA — California</option>
                <option value="UK">United Kingdom</option>
              </select>
            </div>
            <label className="border-2 border-dashed border-gray-300 rounded-xl p-8 text-center cursor-pointer hover:border-blue-400 block">
              {uploading ? (
                <div className="flex flex-col items-center gap-2">
                  <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
                  <p className="text-sm text-gray-500">Uploading…</p>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-2">
                  <Upload className="w-8 h-8 text-gray-400" />
                  <p className="text-sm text-gray-600">Drop PDF here or click to browse</p>
                </div>
              )}
              <input type="file" accept=".pdf" className="hidden"
                onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f); }} />
            </label>
            <div className="flex justify-end mt-4">
              <button onClick={() => setOpen(false)} className="text-sm text-gray-500 hover:text-gray-800 px-3 py-1.5">
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
