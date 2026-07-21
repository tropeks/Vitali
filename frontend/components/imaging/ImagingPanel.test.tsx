import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ImagingPanel } from './ImagingPanel';

vi.mock('@/lib/auth', () => ({ getAccessToken: () => 'token' }));

describe('ImagingPanel', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('queries imaging by laboratory order without assuming Orthanc is available', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify([
          {
            id: 'study-1',
            study_instance_uid: '1.2.3',
            accession_number: 'ACC-1',
            modality: 'CT',
            modality_display: 'Computed Tomography',
            body_part_examined: 'THORAX',
            description: '',
            study_date: '2026-07-21T10:00:00Z',
            number_of_series: 1,
            number_of_instances: 0,
            orthanc_study_id: '',
            has_pixel_data: false,
          },
        ]),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );

    render(<ImagingPanel labOrderId="order-1" />);

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/imaging/studies/?lab_order=order-1',
        expect.objectContaining({ headers: { Authorization: 'Bearer token' } }),
      ),
    );
    expect(await screen.findByText('Aguardando PACS')).toBeInTheDocument();
    expect(screen.queryByTitle(/OHIF Viewer/)).not.toBeInTheDocument();
  });

  it('queries a specific laboratory item', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify([]), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    render(<ImagingPanel labOrderItemId="item-1" />);

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/imaging/studies/?lab_order_item=item-1',
        expect.any(Object),
      ),
    );
  });
});
