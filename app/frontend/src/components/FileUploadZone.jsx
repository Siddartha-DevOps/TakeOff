import React, { useState, useCallback } from 'react';
import { Upload, File, X, Loader2, CheckCircle, AlertCircle } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { uploadsAPI } from '../services/api';

export default function FileUploadZone({ projectId, onUploadComplete }) {
  const [files, setFiles] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [dragActive, setDragActive] = useState(false);

  const handleDrag = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  }, []);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    const droppedFiles = Array.from(e.dataTransfer.files);
    const validFiles = droppedFiles.filter((file) => {
      const ext = file.name.split('.').pop().toLowerCase();
      return ['pdf', 'png', 'jpg', 'jpeg', 'tiff', 'tif'].includes(ext);
    });

    if (validFiles.length > 0) {
      setFiles((prev) => [
        ...prev,
        ...validFiles.map((file) => ({
          file,
          status: 'pending',
          progress: 0,
          id: Math.random().toString(36).substr(2, 9),
        })),
      ]);
    }
  }, []);

  const handleFileInput = (e) => {
    const selectedFiles = Array.from(e.target.files);
    setFiles((prev) => [
      ...prev,
      ...selectedFiles.map((file) => ({
        file,
        status: 'pending',
        progress: 0,
        id: Math.random().toString(36).substr(2, 9),
      })),
    ]);
  };

  const removeFile = (id) => {
    setFiles((prev) => prev.filter((f) => f.id !== id));
  };

  const uploadFiles = async () => {
    if (files.length === 0) return;

    setUploading(true);

    for (const fileItem of files) {
      if (fileItem.status === 'success') continue;

      try {
        setFiles((prev) =>
          prev.map((f) =>
            f.id === fileItem.id ? { ...f, status: 'uploading', progress: 0 } : f
          )
        );

        const progressInterval = setInterval(() => {
          setFiles((prev) =>
            prev.map((f) =>
              f.id === fileItem.id && f.progress < 90
                ? { ...f, progress: f.progress + 10 }
                : f
            )
          );
        }, 200);

        const response = await uploadsAPI.uploadDrawing(
          projectId,
          fileItem.file,
          {
            sheet_name: fileItem.file.name.replace(/\.[^/.]+$/, ''),
            scale: '1/8" = 1\'-0"',
          }
        );

        clearInterval(progressInterval);

        setFiles((prev) =>
          prev.map((f) =>
            f.id === fileItem.id
              ? { ...f, status: 'success', progress: 100, drawing: response.data }
              : f
          )
        );

        if (onUploadComplete) {
          onUploadComplete(response.data);
        }
      } catch (error) {
        console.error('Upload failed:', error);
        setFiles((prev) =>
          prev.map((f) =>
            f.id === fileItem.id
              ? { ...f, status: 'error', progress: 0, error: error.message }
              : f
          )
        );
      }
    }

    setUploading(false);
  };

  const allSuccess = files.length > 0 && files.every((f) => f.status === 'success');

  return (
    <div className="space-y-4">
      {/* Drop Zone */}
      <div
        onDragEnter={handleDrag}
        onDragLeave={handleDrag}
        onDragOver={handleDrag}
        onDrop={handleDrop}
        className={`relative rounded-2xl border-2 border-dashed p-8 text-center transition-all ${
          dragActive
            ? 'border-indigo-500 bg-indigo-50/50'
            : 'border-slate-300 bg-slate-50/60 hover:border-slate-400'
        }`}
      >
        <input
          type="file"
          id="file-upload"
          multiple
          accept=".pdf,.png,.jpg,.jpeg,.tiff,.tif"
          onChange={handleFileInput}
          className="hidden"
        />

        <Upload className="w-10 h-10 text-slate-400 mx-auto mb-3" />
        <h3 className="text-sm font-semibold text-slate-900">
          Drop blueprints here or{' '}
          <label htmlFor="file-upload" className="text-indigo-600 cursor-pointer hover:text-indigo-700">
            browse
          </label>
        </h3>
        <p className="mt-1 text-xs text-slate-500">
          Supports PDF, TIFF, PNG, JPG up to 500MB
        </p>
      </div>

      {/* File List */}
      <AnimatePresence>
        {files.length > 0 && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="space-y-2"
          >
            {files.map((fileItem) => (
              <motion.div
                key={fileItem.id}
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: 20 }}
                className="flex items-center gap-3 p-3 rounded-lg bg-white border border-slate-200"
              >
                <div className="flex-shrink-0">
                  {fileItem.status === 'success' ? (
                    <CheckCircle className="w-5 h-5 text-emerald-600" />
                  ) : fileItem.status === 'error' ? (
                    <AlertCircle className="w-5 h-5 text-rose-600" />
                  ) : fileItem.status === 'uploading' ? (
                    <Loader2 className="w-5 h-5 text-indigo-600 animate-spin" />
                  ) : (
                    <File className="w-5 h-5 text-slate-400" />
                  )}
                </div>

                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-slate-900 truncate">
                      {fileItem.file.name}
                    </span>
                    <span className="text-xs text-slate-500 ml-2">
                      {(fileItem.file.size / 1024 / 1024).toFixed(2)} MB
                    </span>
                  </div>

                  {fileItem.status === 'uploading' && (
                    <div className="mt-1.5 h-1 bg-slate-100 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-indigo-600 transition-all duration-300"
                        style={{ width: `${fileItem.progress}%` }}
                      />
                    </div>
                  )}

                  {fileItem.status === 'error' && (
                    <p className="mt-1 text-xs text-rose-600">{fileItem.error}</p>
                  )}

                  {fileItem.status === 'success' && (
                    <p className="mt-1 text-xs text-emerald-600">Upload complete</p>
                  )}
                </div>

                {fileItem.status === 'pending' && (
                  <button
                    onClick={() => removeFile(fileItem.id)}
                    className="flex-shrink-0 w-6 h-6 rounded hover:bg-slate-100 flex items-center justify-center text-slate-400"
                  >
                    <X className="w-4 h-4" />
                  </button>
                )}
              </motion.div>
            ))}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Upload Button */}
      {files.length > 0 && !allSuccess && (
        <button
          onClick={uploadFiles}
          disabled={uploading}
          className="w-full py-2.5 rounded-lg bg-slate-900 text-white text-sm font-medium hover:bg-slate-800 disabled:opacity-50 flex items-center justify-center gap-2"
        >
          {uploading ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              Uploading...
            </>
          ) : (
            <>
              <Upload className="w-4 h-4" />
              Upload {files.length} file{files.length > 1 ? 's' : ''}
            </>
          )}
        </button>
      )}
    </div>
  );
}