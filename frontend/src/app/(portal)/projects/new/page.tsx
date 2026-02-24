'use client';

import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import { gisApi, projectsApi } from '@/lib/api';
import { ChevronRight, ChevronLeft, Check, Locate } from 'lucide-react';
import { cn } from '@/lib/utils';

// ---- Step schemas ----

const step1Schema = z.object({
  name: z.string().min(2, 'Project name is required'),
  client_name: z.string().optional(),
  site_address: z.string().optional(),
  city: z.string().min(1, 'City is required'),
  country: z.string().min(1, 'Country is required'),
});

const step2Schema = z.object({
  jurisdiction: z.string().min(1, 'Jurisdiction is required'),
  road_width_m: z.coerce.number().min(0).optional(),
  num_floors: z.coerce.number().int().min(1).max(10).optional(),
  local_body: z.string().optional(),
  site_lat: z.coerce.number().min(-90).max(90).optional(),
  site_lon: z.coerce.number().min(-180).max(180).optional(),
});

const step3Schema = z.object({
  dimension_units: z.enum(['metric', 'imperial']).default('metric'),
  style: z.enum(['modern', 'traditional', 'minimal', 'newari', 'classical']).default('modern'),
  vastu_compliant: z.boolean().default(false),
  seismic_zone: z.string().default('V'),
});

type Step1 = z.infer<typeof step1Schema>;
type Step2 = z.infer<typeof step2Schema>;
type Step3 = z.infer<typeof step3Schema>;

const JURISDICTIONS = [
  { value: 'NP-KTM',     label: 'Nepal — Kathmandu (NBC 2020)' },
  { value: 'NP-LAL',     label: 'Nepal — Lalitpur (NBC 2020)' },
  { value: 'NP-BKT',     label: 'Nepal — Bhaktapur (NBC 2020)' },
  { value: 'NP-PKR',     label: 'Nepal — Pokhara (NBC 2020)' },
  { value: 'NP',         label: 'Nepal — Other (NBC 2020)' },
  { value: 'IN-MH',      label: 'India — Maharashtra (NBC 2016)' },
  { value: 'IN-MH-PUN',  label: 'India — Pune / PCMC (NBC 2016)' },
  { value: 'IN-KA',      label: 'India — Karnataka (NBC 2016)' },
  { value: 'IN',         label: 'India — Other (NBC 2016)' },
  { value: 'US-CA',      label: 'USA — California (CBC 2022)' },
  { value: 'UK',         label: 'United Kingdom (Building Regs 2023)' },
];

const STEPS = ['Basic Info', 'Jurisdiction', 'Options'];

export default function NewProjectPage() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [step1Data, setStep1Data] = useState<Step1 | null>(null);
  const [step2Data, setStep2Data] = useState<Step2 | null>(null);
  const [isDetecting, setIsDetecting] = useState(false);
  const [detectionResult, setDetectionResult] = useState<string | null>(null);

  const form1 = useForm<Step1>({ resolver: zodResolver(step1Schema) });
  const form2 = useForm<Step2>({ resolver: zodResolver(step2Schema) });
  const form3 = useForm<Step3>({ resolver: zodResolver(step3Schema) });

  async function handleStep1(data: Step1) {
    setStep1Data(data);
    setStep(1);
  }

  async function handleAutoDetect() {
    const lat = form2.getValues('site_lat');
    const lon = form2.getValues('site_lon');
    if (lat === undefined || lon === undefined || lat === null || lon === null) {
      toast.error('Enter latitude and longitude first.');
      return;
    }
    setIsDetecting(true);
    setDetectionResult(null);
    try {
      const result = await gisApi.resolveJurisdiction(lat, lon);
      form2.setValue('jurisdiction', result.jurisdiction);
      if (result.local_body) {
        form2.setValue('local_body', result.local_body);
      }
      const pct = Math.round(result.confidence * 100);
      setDetectionResult(
        `Detected: ${result.jurisdiction}${result.local_body ? ` / ${result.local_body}` : ''} — ${pct}% confidence (${result.match_level})`
      );
      toast.success('Jurisdiction auto-detected!');
    } catch {
      toast.error('Could not detect jurisdiction. Check your coordinates and try again.');
    } finally {
      setIsDetecting(false);
    }
  }

  async function handleStep2(data: Step2) {
    setStep2Data(data);
    setStep(2);
  }

  async function handleStep3(data: Step3) {
    if (!step1Data || !step2Data) return;
    try {
      const project = await projectsApi.create({
        name: step1Data.name,
        client_name: step1Data.client_name ?? '',
        properties: {
          site_address: step1Data.site_address,
          city: step1Data.city,
          country: step1Data.country,
          jurisdiction: step2Data.jurisdiction,
          road_width_m: step2Data.road_width_m,
          num_floors: step2Data.num_floors ?? 2,
          local_body: step2Data.local_body,
          site_lat: step2Data.site_lat,
          site_lon: step2Data.site_lon,
          dimension_units: data.dimension_units,
          style: data.style,
          vastu_compliant: data.vastu_compliant,
          seismic_zone: data.seismic_zone,
        },
      }) as { id: string };
      toast.success('Project created!');
      router.push(`/projects/${project.id}/plot`);
    } catch {
      toast.error('Failed to create project. Please try again.');
    }
  }

  return (
    <div className="max-w-2xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">New Project</h1>
        <p className="text-gray-500 text-sm mt-1">Set up your project in 3 steps</p>
      </div>

      {/* Step indicator */}
      <div className="flex items-center mb-8">
        {STEPS.map((label, i) => (
          <div key={label} className="flex items-center">
            <div className="flex items-center gap-2">
              <div className={cn(
                'w-7 h-7 rounded-full flex items-center justify-center text-xs font-semibold',
                i < step ? 'bg-blue-600 text-white' : i === step ? 'bg-blue-100 text-blue-700 border-2 border-blue-600' : 'bg-gray-100 text-gray-400'
              )}>
                {i < step ? <Check className="w-3.5 h-3.5" /> : i + 1}
              </div>
              <span className={cn('text-sm font-medium', i === step ? 'text-blue-700' : i < step ? 'text-gray-600' : 'text-gray-400')}>{label}</span>
            </div>
            {i < STEPS.length - 1 && <div className="h-px w-8 bg-gray-200 mx-3" />}
          </div>
        ))}
      </div>

      <div className="bg-white rounded-xl border border-gray-200 p-6">
        {/* Step 1 */}
        {step === 0 && (
          <form onSubmit={form1.handleSubmit(handleStep1)} className="space-y-4">
            <h2 className="font-semibold text-gray-900 mb-4">Basic Information</h2>
            <Field label="Project name *" error={form1.formState.errors.name?.message}>
              <input {...form1.register('name')} placeholder="Smith Residence" className={inputClass} />
            </Field>
            <Field label="Client name" error={form1.formState.errors.client_name?.message}>
              <input {...form1.register('client_name')} placeholder="John Smith" className={inputClass} />
            </Field>
            <Field label="Site address" error={form1.formState.errors.site_address?.message}>
              <input {...form1.register('site_address')} placeholder="123 Main St" className={inputClass} />
            </Field>
            <div className="grid grid-cols-2 gap-4">
              <Field label="City *" error={form1.formState.errors.city?.message}>
                <input {...form1.register('city')} placeholder="Kathmandu" className={inputClass} />
              </Field>
              <Field label="Country *" error={form1.formState.errors.country?.message}>
                <input {...form1.register('country')} placeholder="Nepal" className={inputClass} />
              </Field>
            </div>
            <StepNav canBack={false} onBack={() => {}} />
          </form>
        )}

        {/* Step 2 */}
        {step === 1 && (
          <form onSubmit={form2.handleSubmit(handleStep2)} className="space-y-4">
            <h2 className="font-semibold text-gray-900 mb-4">Jurisdiction & Site</h2>

            {/* GPS auto-detect block */}
            <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 space-y-3">
              <p className="text-xs font-medium text-gray-600">
                Auto-detect jurisdiction from GPS coordinates (optional)
              </p>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Latitude" error={form2.formState.errors.site_lat?.message}>
                  <input
                    {...form2.register('site_lat')}
                    type="number"
                    step="any"
                    placeholder="27.7172"
                    className={inputClass}
                  />
                </Field>
                <Field label="Longitude" error={form2.formState.errors.site_lon?.message}>
                  <input
                    {...form2.register('site_lon')}
                    type="number"
                    step="any"
                    placeholder="85.3240"
                    className={inputClass}
                  />
                </Field>
              </div>
              <button
                type="button"
                onClick={handleAutoDetect}
                disabled={isDetecting}
                className="flex items-center gap-2 px-3 py-1.5 text-xs font-medium text-blue-700 bg-blue-50 border border-blue-200 rounded-md hover:bg-blue-100 disabled:opacity-50"
              >
                <Locate className="w-3.5 h-3.5" />
                {isDetecting ? 'Detecting…' : 'Auto-detect jurisdiction'}
              </button>
              {detectionResult && (
                <p className="text-xs text-green-700 font-medium">{detectionResult}</p>
              )}
            </div>

            <Field label="Jurisdiction *" error={form2.formState.errors.jurisdiction?.message}>
              <select {...form2.register('jurisdiction')} className={inputClass} defaultValue="NP-KTM">
                {JURISDICTIONS.map((j) => (
                  <option key={j.value} value={j.value}>{j.label}</option>
                ))}
              </select>
            </Field>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Number of floors" error={form2.formState.errors.num_floors?.message}>
                <input {...form2.register('num_floors')} type="number" min={1} max={10} placeholder="2" className={inputClass} />
              </Field>
              <Field label="Road width (m)" error={form2.formState.errors.road_width_m?.message}>
                <input {...form2.register('road_width_m')} type="number" step="0.5" placeholder="6.0" className={inputClass} />
              </Field>
            </div>
            <Field label="Local body / ward" error={form2.formState.errors.local_body?.message}>
              <input {...form2.register('local_body')} placeholder="Ward No. 5" className={inputClass} />
            </Field>
            <StepNav canBack onBack={() => setStep(0)} />
          </form>
        )}

        {/* Step 3 */}
        {step === 2 && (
          <form onSubmit={form3.handleSubmit(handleStep3)} className="space-y-4">
            <h2 className="font-semibold text-gray-900 mb-4">Design Options</h2>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Units" error={undefined}>
                <select {...form3.register('dimension_units')} className={inputClass}>
                  <option value="metric">Metric (m)</option>
                  <option value="imperial">Imperial (ft)</option>
                </select>
              </Field>
              <Field label="Architectural style" error={undefined}>
                <select {...form3.register('style')} className={inputClass}>
                  <option value="modern">Modern</option>
                  <option value="traditional">Traditional</option>
                  <option value="minimal">Minimal</option>
                  <option value="newari">Newari</option>
                  <option value="classical">Classical</option>
                </select>
              </Field>
            </div>
            <Field label="Seismic zone" error={undefined}>
              <select {...form3.register('seismic_zone')} className={inputClass}>
                <option value="V">Zone V (Very high — Nepal default)</option>
                <option value="IV">Zone IV (High)</option>
                <option value="III">Zone III (Moderate)</option>
                <option value="II">Zone II (Low to moderate)</option>
              </select>
            </Field>
            <label className="flex items-center gap-3 cursor-pointer">
              <input {...form3.register('vastu_compliant')} type="checkbox" className="w-4 h-4 rounded text-blue-600" />
              <span className="text-sm text-gray-700">Apply Vastu Shastra guidelines</span>
            </label>
            <StepNav canBack onBack={() => setStep(1)} submitLabel="Create Project" isSubmitting={form3.formState.isSubmitting} />
          </form>
        )}
      </div>
    </div>
  );
}

function Field({ label, error, children }: { label: string; error?: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-600 mb-1">{label}</label>
      {children}
      {error && <p className="text-red-500 text-xs mt-1">{error}</p>}
    </div>
  );
}

const inputClass = 'w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500';

function StepNav({
  canBack, onBack, submitLabel = 'Continue', isSubmitting = false,
}: {
  canBack: boolean;
  onBack: () => void;
  submitLabel?: string;
  isSubmitting?: boolean;
}) {
  return (
    <div className="flex justify-between pt-4 border-t border-gray-100 mt-6">
      {canBack ? (
        <button type="button" onClick={onBack} className="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-800">
          <ChevronLeft className="w-4 h-4" /> Back
        </button>
      ) : <div />}
      <button
        type="submit"
        disabled={isSubmitting}
        className="flex items-center gap-1.5 px-5 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
      >
        {isSubmitting ? 'Creating…' : submitLabel}
        {!isSubmitting && <ChevronRight className="w-4 h-4" />}
      </button>
    </div>
  );
}
