-- +goose Up
UPDATE public.tiers
SET disk_mb = 8192
WHERE id = 'base_v1' AND disk_mb < 8192;

-- +goose Down
UPDATE public.tiers
SET disk_mb = 512
WHERE id = 'base_v1' AND disk_mb = 8192;
