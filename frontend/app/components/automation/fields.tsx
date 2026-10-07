import React from 'react';
import TextField from '@mui/material/TextField';
import InputAdornment from '@mui/material/InputAdornment';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Switch from '@mui/material/Switch';

import { filledFieldSx } from '../../../src/automation';

// 配置表单里反复出现的几种输入框

interface NumberFieldProps {
  label: string;
  value: number | null | undefined;
  onChange: (value: number | null) => void;
  error?: string;
  helper?: React.ReactNode;
  unit?: string;
  step?: number;
}

export const NumberField = ({ label, value, onChange, error, helper, unit, step = 1 }: NumberFieldProps) => (
  <TextField
    fullWidth
    variant="filled"
    type="number"
    label={label}
    value={value ?? ''}
    onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}
    error={!!error}
    helperText={error || helper}
    slotProps={{
      input: {
        disableUnderline: true,
        endAdornment: unit ? <InputAdornment position="end">{unit}</InputAdornment> : undefined,
      },
      htmlInput: { step },
    }}
    sx={filledFieldSx}
  />
);

interface TextFieldRowProps {
  label: string;
  value: string | null | undefined;
  onChange: (value: string) => void;
  error?: string;
  helper?: React.ReactNode;
  placeholder?: string;
  multiline?: boolean;
}

export const TextInput = ({ label, value, onChange, error, helper, placeholder, multiline }: TextFieldRowProps) => (
  <TextField
    fullWidth
    variant="filled"
    label={label}
    value={value ?? ''}
    placeholder={placeholder}
    onChange={(e) => onChange(e.target.value)}
    error={!!error}
    helperText={error || helper}
    multiline={multiline}
    minRows={multiline ? 2 : undefined}
    slotProps={{ input: { disableUnderline: true } }}
    sx={filledFieldSx}
  />
);

interface SwitchRowProps {
  label: string;
  description?: React.ReactNode;
  checked: boolean;
  onChange: (checked: boolean) => void;
}

export const SwitchRow = ({ label, description, checked, onChange }: SwitchRowProps) => (
  <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 2 }}>
    <Box>
      <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>{label}</Typography>
      {description && <Typography variant="caption" color="text.secondary">{description}</Typography>}
    </Box>
    <Switch checked={!!checked} onChange={(e) => onChange(e.target.checked)} color="secondary" />
  </Box>
);

export const SectionTitle = ({ icon, title, children }: { icon?: React.ReactNode; title: string; children?: React.ReactNode }) => (
  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 0.5 }}>
    {icon}
    <Typography variant="subtitle1" sx={{ fontWeight: 900, flex: 1 }}>{title}</Typography>
    {children}
  </Box>
);
