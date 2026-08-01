BEGIN;

CREATE TABLE exhibition.exhibitor (
	exhibitor_id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	company_name VARCHAR(200) NOT NULL,
	business_registration_hmac BYTEA,
	company_summary TEXT,
	business_type_taxonomy_version_id UUID,
	business_type_concept_id UUID,
	region_taxonomy_version_id UUID,
	region_concept_id UUID,
	website_url TEXT,
	master_approval_status VARCHAR(20) NOT NULL,
	data_completeness_percent NUMERIC(5, 2) NOT NULL,
	current_profile_version INTEGER NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	deleted_at TIMESTAMP WITH TIME ZONE,
	CONSTRAINT pk_exhibitor PRIMARY KEY (exhibitor_id),
	CONSTRAINT fk_exhibitor_business_type_ontology_revision FOREIGN KEY(business_type_taxonomy_version_id, business_type_concept_id) REFERENCES ontology.concept_revision (taxonomy_version_id, concept_id),
	CONSTRAINT fk_exhibitor_region_ontology_revision FOREIGN KEY(region_taxonomy_version_id, region_concept_id) REFERENCES ontology.concept_revision (taxonomy_version_id, concept_id),
	CONSTRAINT ck_exhibitor_master_approval_status_allowed CHECK (master_approval_status IN ('DRAFT', 'APPROVED', 'REJECTED')),
	CONSTRAINT ck_exhibitor_data_completeness_percent_range CHECK (data_completeness_percent >= 0 AND data_completeness_percent <= 100),
	CONSTRAINT ck_exhibitor_business_type_pair_complete CHECK (num_nonnulls(business_type_taxonomy_version_id, business_type_concept_id) IN (0, 2)),
	CONSTRAINT ck_exhibitor_region_pair_complete CHECK (num_nonnulls(region_taxonomy_version_id, region_concept_id) IN (0, 2)),
	CONSTRAINT uq_exhibitor_tenant_id UNIQUE (tenant_id, exhibitor_id),
	CONSTRAINT fk_exhibitor_tenant_id_tenant FOREIGN KEY(tenant_id) REFERENCES core.tenant (tenant_id)
);

CREATE INDEX ix_exhibitor_tenant ON exhibition.exhibitor (tenant_id);

CREATE TABLE exhibition.profile_attribute (
	supply_attribute_id UUID NOT NULL,
	object_type VARCHAR(20) NOT NULL,
	object_id UUID NOT NULL,
	taxonomy_version_id UUID NOT NULL,
	concept_id UUID NOT NULL,
	attribute_code VARCHAR(100) NOT NULL,
	value_json JSONB NOT NULL,
	source_type VARCHAR(30) NOT NULL,
	verification_status VARCHAR(20) NOT NULL,
	confidence NUMERIC(4, 3) NOT NULL,
	visibility VARCHAR(30) NOT NULL,
	valid_from TIMESTAMP WITH TIME ZONE,
	valid_until TIMESTAMP WITH TIME ZONE,
	active BOOLEAN NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_profile_attribute PRIMARY KEY (supply_attribute_id),
	CONSTRAINT fk_supply_profile_attribute_ontology_revision FOREIGN KEY(taxonomy_version_id, concept_id) REFERENCES ontology.concept_revision (taxonomy_version_id, concept_id),
	CONSTRAINT ck_profile_attribute_object_type_allowed CHECK (object_type IN ('EXHIBITOR', 'PRODUCT', 'TRADE_CONDITION')),
	CONSTRAINT ck_profile_attribute_source_type_allowed CHECK (source_type IN ('EXHIBITOR_ENTERED', 'EXHIBITOR_CONFIRMED', 'OPERATOR_ENTERED', 'OPERATOR_VERIFIED', 'AI_EXTRACTED', 'EXTERNAL_SYNC', 'DOCUMENT_VERIFIED', 'SYSTEM_CALCULATED', 'REALTIME_OPERATION', 'USER_FEEDBACK')),
	CONSTRAINT ck_profile_attribute_verification_status_allowed CHECK (verification_status IN ('SELF_DECLARED', 'DOCUMENT_SUBMITTED', 'OPERATOR_REVIEWED', 'VERIFIED', 'EXPIRED', 'REJECTED')),
	CONSTRAINT ck_profile_attribute_confidence_range CHECK (confidence >= 0 AND confidence <= 1),
	CONSTRAINT ck_profile_attribute_visibility_allowed CHECK (visibility IN ('PUBLIC', 'BUYER_ONLY', 'MATCHED_BUYER_ONLY', 'MEETING_ACCEPTED', 'PRIVATE')),
	CONSTRAINT ck_profile_attribute_valid_period_order CHECK (valid_from IS NULL OR valid_until IS NULL OR valid_from <= valid_until)
);

CREATE INDEX ix_supply_profile_attribute_lookup ON exhibition.profile_attribute (object_type, object_id, taxonomy_version_id, concept_id, active);

CREATE TABLE exhibition.buyer_preference (
	exhibitor_buyer_preference_id UUID NOT NULL,
	exhibitor_id UUID NOT NULL,
	taxonomy_version_id UUID NOT NULL,
	buyer_type_concept_id UUID,
	channel_concept_id UUID,
	region_concept_id UUID,
	volume_min INTEGER,
	volume_max INTEGER,
	preference_level VARCHAR(20) NOT NULL,
	active BOOLEAN NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_buyer_preference PRIMARY KEY (exhibitor_buyer_preference_id),
	CONSTRAINT fk_buyer_preference_buyer_type_ontology_revision FOREIGN KEY(taxonomy_version_id, buyer_type_concept_id) REFERENCES ontology.concept_revision (taxonomy_version_id, concept_id),
	CONSTRAINT fk_buyer_preference_channel_ontology_revision FOREIGN KEY(taxonomy_version_id, channel_concept_id) REFERENCES ontology.concept_revision (taxonomy_version_id, concept_id),
	CONSTRAINT fk_buyer_preference_region_ontology_revision FOREIGN KEY(taxonomy_version_id, region_concept_id) REFERENCES ontology.concept_revision (taxonomy_version_id, concept_id),
	CONSTRAINT ck_buyer_preference_at_least_one_dimension CHECK (num_nonnulls(buyer_type_concept_id, channel_concept_id, region_concept_id) >= 1),
	CONSTRAINT ck_buyer_preference_volume_min_nonneg CHECK (volume_min IS NULL OR volume_min >= 0),
	CONSTRAINT ck_buyer_preference_volume_max_nonneg CHECK (volume_max IS NULL OR volume_max >= 0),
	CONSTRAINT ck_buyer_preference_volume_order CHECK (volume_min IS NULL OR volume_max IS NULL OR volume_min <= volume_max),
	CONSTRAINT ck_buyer_preference_preference_level_allowed CHECK (preference_level IN ('REQUIRED', 'PREFERRED', 'EXCLUDED')),
	CONSTRAINT fk_buyer_preference_exhibitor_id_exhibitor FOREIGN KEY(exhibitor_id) REFERENCES exhibition.exhibitor (exhibitor_id)
);

CREATE TABLE exhibition.exhibitor_business_type (
	exhibitor_business_type_id UUID NOT NULL,
	exhibitor_id UUID NOT NULL,
	taxonomy_version_id UUID NOT NULL,
	concept_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_exhibitor_business_type PRIMARY KEY (exhibitor_business_type_id),
	CONSTRAINT fk_exhibitor_business_type_ontology_revision FOREIGN KEY(taxonomy_version_id, concept_id) REFERENCES ontology.concept_revision (taxonomy_version_id, concept_id),
	CONSTRAINT uq_exhibitor_business_type_concept UNIQUE (exhibitor_id, taxonomy_version_id, concept_id),
	CONSTRAINT fk_exhibitor_business_type_exhibitor_id_exhibitor FOREIGN KEY(exhibitor_id) REFERENCES exhibition.exhibitor (exhibitor_id)
);

CREATE TABLE exhibition.exhibitor_participation (
	participation_id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	event_id UUID NOT NULL,
	exhibitor_id UUID NOT NULL,
	participation_status VARCHAR(20) NOT NULL,
	promotion_summary TEXT,
	consultation_enabled BOOLEAN NOT NULL,
	approved_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_exhibitor_participation PRIMARY KEY (participation_id),
	CONSTRAINT fk_exhibitor_participation_event_boundary FOREIGN KEY(tenant_id, event_id) REFERENCES exhibition.event (tenant_id, event_id),
	CONSTRAINT fk_exhibitor_participation_exhibitor_boundary FOREIGN KEY(tenant_id, exhibitor_id) REFERENCES exhibition.exhibitor (tenant_id, exhibitor_id),
	CONSTRAINT uq_exhibitor_participation_event UNIQUE (event_id, exhibitor_id),
	CONSTRAINT uq_exhibitor_participation_boundary_id UNIQUE (tenant_id, event_id, participation_id),
	CONSTRAINT ck_exhibitor_participation_participation_status_allowed CHECK (participation_status IN ('APPLIED', 'APPROVED', 'CANCELLED'))
);

CREATE TABLE exhibition.exhibitor_profile (
	exhibitor_profile_id UUID NOT NULL,
	exhibitor_id UUID NOT NULL,
	business_type JSONB,
	capability_json JSONB,
	preferred_buyer_json JSONB,
	trade_readiness_score NUMERIC(5, 2),
	consumer_completeness NUMERIC(5, 2) NOT NULL,
	buyer_completeness NUMERIC(5, 2) NOT NULL,
	current_version INTEGER NOT NULL,
	approval_status VARCHAR(20) NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_exhibitor_profile PRIMARY KEY (exhibitor_profile_id),
	CONSTRAINT ck_exhibitor_profile_trade_readiness_score_range CHECK (trade_readiness_score IS NULL OR (trade_readiness_score >= 0 AND trade_readiness_score <= 100)),
	CONSTRAINT ck_exhibitor_profile_consumer_completeness_range CHECK (consumer_completeness >= 0 AND consumer_completeness <= 100),
	CONSTRAINT ck_exhibitor_profile_buyer_completeness_range CHECK (buyer_completeness >= 0 AND buyer_completeness <= 100),
	CONSTRAINT ck_exhibitor_profile_approval_status_allowed CHECK (approval_status IN ('DRAFT', 'SUBMITTED', 'APPROVED', 'REJECTED')),
	CONSTRAINT uq_exhibitor_profile_exhibitor_id UNIQUE (exhibitor_id),
	CONSTRAINT fk_exhibitor_profile_exhibitor_id_exhibitor FOREIGN KEY(exhibitor_id) REFERENCES exhibition.exhibitor (exhibitor_id)
);

CREATE TABLE exhibition.product (
	product_id UUID NOT NULL,
	exhibitor_id UUID NOT NULL,
	product_name VARCHAR(200) NOT NULL,
	category_taxonomy_version_id UUID,
	category_concept_id UUID,
	product_summary TEXT,
	alcohol_percentage NUMERIC(5, 2),
	main_ingredients_json JSONB,
	production_method TEXT,
	master_approval_status VARCHAR(20) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	deleted_at TIMESTAMP WITH TIME ZONE,
	CONSTRAINT pk_product PRIMARY KEY (product_id),
	CONSTRAINT fk_product_category_ontology_revision FOREIGN KEY(category_taxonomy_version_id, category_concept_id) REFERENCES ontology.concept_revision (taxonomy_version_id, concept_id),
	CONSTRAINT ck_product_alcohol_percentage_range CHECK (alcohol_percentage IS NULL OR (alcohol_percentage >= 0 AND alcohol_percentage <= 100)),
	CONSTRAINT ck_product_master_approval_status_allowed CHECK (master_approval_status IN ('DRAFT', 'APPROVED', 'REJECTED')),
	CONSTRAINT ck_product_category_pair_complete CHECK (num_nonnulls(category_taxonomy_version_id, category_concept_id) IN (0, 2)),
	CONSTRAINT fk_product_exhibitor_id_exhibitor FOREIGN KEY(exhibitor_id) REFERENCES exhibition.exhibitor (exhibitor_id)
);

CREATE INDEX idx_product_category ON exhibition.product (category_taxonomy_version_id, category_concept_id) WHERE deleted_at IS NULL AND master_approval_status = 'APPROVED';

CREATE TABLE exhibition.program (
	program_id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	event_id UUID NOT NULL,
	zone_id UUID,
	program_name VARCHAR(200) NOT NULL,
	program_type VARCHAR(30),
	start_at TIMESTAMP WITH TIME ZONE,
	end_at TIMESTAMP WITH TIME ZONE,
	capacity INTEGER,
	reservation_required BOOLEAN NOT NULL,
	status VARCHAR(20) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_program PRIMARY KEY (program_id),
	CONSTRAINT fk_program_event_boundary FOREIGN KEY(tenant_id, event_id) REFERENCES exhibition.event (tenant_id, event_id),
	CONSTRAINT fk_program_zone_same_event FOREIGN KEY(tenant_id, event_id, zone_id) REFERENCES exhibition.event_zone (tenant_id, event_id, event_zone_id),
	CONSTRAINT ck_program_time_range CHECK (start_at IS NULL OR end_at IS NULL OR start_at < end_at),
	CONSTRAINT ck_program_capacity_nonneg CHECK (capacity IS NULL OR capacity >= 0),
	CONSTRAINT ck_program_status_allowed CHECK (status IN ('PLANNED', 'OPEN', 'CLOSED', 'CANCELLED'))
);

CREATE TABLE exhibition.booth (
	booth_id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	event_id UUID NOT NULL,
	participation_id UUID NOT NULL,
	zone_id UUID,
	booth_number VARCHAR(30) NOT NULL,
	map_x NUMERIC(10, 3),
	map_y NUMERIC(10, 3),
	operating_status VARCHAR(20) NOT NULL,
	congestion_level VARCHAR(20) NOT NULL,
	estimated_wait_minutes INTEGER,
	status_observed_at TIMESTAMP WITH TIME ZONE,
	row_version BIGINT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_booth PRIMARY KEY (booth_id),
	CONSTRAINT fk_booth_event_boundary FOREIGN KEY(tenant_id, event_id) REFERENCES exhibition.event (tenant_id, event_id),
	CONSTRAINT fk_booth_zone_same_event FOREIGN KEY(tenant_id, event_id, zone_id) REFERENCES exhibition.event_zone (tenant_id, event_id, event_zone_id),
	CONSTRAINT fk_booth_participation_boundary FOREIGN KEY(tenant_id, event_id, participation_id) REFERENCES exhibition.exhibitor_participation (tenant_id, event_id, participation_id),
	CONSTRAINT uq_booth_event_number UNIQUE (event_id, booth_number),
	CONSTRAINT ck_booth_operating_status_allowed CHECK (operating_status IN ('OPEN', 'PAUSED', 'CLOSED')),
	CONSTRAINT ck_booth_congestion_level_allowed CHECK (congestion_level IN ('LOW', 'MEDIUM', 'HIGH', 'UNKNOWN')),
	CONSTRAINT ck_booth_estimated_wait_minutes_nonneg CHECK (estimated_wait_minutes IS NULL OR estimated_wait_minutes >= 0)
);

CREATE INDEX idx_booth_live ON exhibition.booth (event_id, operating_status, congestion_level);

CREATE TABLE exhibition.event_product (
	event_product_id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	event_id UUID NOT NULL,
	participation_id UUID NOT NULL,
	product_id UUID NOT NULL,
	retail_price_amount BIGINT,
	event_price_amount BIGINT,
	currency CHAR(3) NOT NULL,
	tasting_status VARCHAR(20) NOT NULL,
	purchase_status VARCHAR(20) NOT NULL,
	inventory_status VARCHAR(20) NOT NULL,
	status_observed_at TIMESTAMP WITH TIME ZONE,
	approval_status VARCHAR(20) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_event_product PRIMARY KEY (event_product_id),
	CONSTRAINT fk_event_product_event_boundary FOREIGN KEY(tenant_id, event_id) REFERENCES exhibition.event (tenant_id, event_id),
	CONSTRAINT fk_event_product_participation_boundary FOREIGN KEY(tenant_id, event_id, participation_id) REFERENCES exhibition.exhibitor_participation (tenant_id, event_id, participation_id),
	CONSTRAINT uq_event_product_event_product UNIQUE (event_id, product_id),
	CONSTRAINT uq_event_product_boundary_id UNIQUE (tenant_id, event_id, event_product_id),
	CONSTRAINT ck_event_product_retail_price_amount_nonneg CHECK (retail_price_amount IS NULL OR retail_price_amount >= 0),
	CONSTRAINT ck_event_product_event_price_amount_nonneg CHECK (event_price_amount IS NULL OR event_price_amount >= 0),
	CONSTRAINT ck_event_product_tasting_status_allowed CHECK (tasting_status IN ('AVAILABLE', 'PAUSED', 'ENDED')),
	CONSTRAINT ck_event_product_purchase_status_allowed CHECK (purchase_status IN ('AVAILABLE', 'LIMITED', 'ENDED')),
	CONSTRAINT ck_event_product_inventory_status_allowed CHECK (inventory_status IN ('AVAILABLE', 'LOW', 'SOLD_OUT', 'UNKNOWN')),
	CONSTRAINT ck_event_product_approval_status_allowed CHECK (approval_status IN ('DRAFT', 'APPROVED', 'REJECTED')),
	CONSTRAINT fk_event_product_product_id_product FOREIGN KEY(product_id) REFERENCES exhibition.product (product_id)
);

CREATE INDEX idx_event_product_filter ON exhibition.event_product (event_id, approval_status, inventory_status, tasting_status, purchase_status);

CREATE TABLE exhibition.exhibitor_staff (
	staff_id UUID NOT NULL,
	participation_id UUID NOT NULL,
	user_id UUID,
	display_name VARCHAR(100) NOT NULL,
	position_name VARCHAR(100),
	active BOOLEAN NOT NULL,
	CONSTRAINT pk_exhibitor_staff PRIMARY KEY (staff_id),
	CONSTRAINT fk_exhibitor_staff_participation_id_exhibitor_participation FOREIGN KEY(participation_id) REFERENCES exhibition.exhibitor_participation (participation_id),
	CONSTRAINT fk_exhibitor_staff_user_id_user_account FOREIGN KEY(user_id) REFERENCES profile.user_account (user_id)
);

CREATE TABLE exhibition.participation_category (
	participation_id UUID NOT NULL,
	taxonomy_version_id UUID NOT NULL,
	concept_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_participation_category PRIMARY KEY (participation_id, taxonomy_version_id, concept_id),
	CONSTRAINT fk_participation_category_ontology_revision FOREIGN KEY(taxonomy_version_id, concept_id) REFERENCES ontology.concept_revision (taxonomy_version_id, concept_id),
	CONSTRAINT fk_participation_category_participation_id_exhibitor_pa_fe7b FOREIGN KEY(participation_id) REFERENCES exhibition.exhibitor_participation (participation_id)
);

CREATE TABLE exhibition.product_attribute (
	product_attribute_id UUID NOT NULL,
	product_id UUID NOT NULL,
	taxonomy_version_id UUID NOT NULL,
	concept_id UUID NOT NULL,
	numeric_value NUMERIC,
	text_value TEXT,
	source VARCHAR(20) NOT NULL,
	confidence NUMERIC(4, 3),
	review_status VARCHAR(20) NOT NULL,
	ai_run_id UUID,
	evidence_ref JSONB,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_product_attribute PRIMARY KEY (product_attribute_id),
	CONSTRAINT fk_product_attribute_ontology_revision FOREIGN KEY(taxonomy_version_id, concept_id) REFERENCES ontology.concept_revision (taxonomy_version_id, concept_id),
	CONSTRAINT ck_product_attribute_exactly_one_value CHECK (num_nonnulls(numeric_value, text_value) = 1),
	CONSTRAINT ck_product_attribute_source_allowed CHECK (source IN ('EXHIBITOR', 'AI', 'OPERATOR')),
	CONSTRAINT ck_product_attribute_confidence_range CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
	CONSTRAINT ck_product_attribute_review_status_allowed CHECK (review_status IN ('PENDING', 'APPROVED', 'REJECTED')),
	CONSTRAINT fk_product_attribute_product_id_product FOREIGN KEY(product_id) REFERENCES exhibition.product (product_id)
);

CREATE INDEX ix_product_attribute_lookup ON exhibition.product_attribute (product_id, taxonomy_version_id, concept_id);

CREATE TABLE exhibition.product_image (
	product_image_id UUID NOT NULL,
	product_id UUID NOT NULL,
	storage_key VARCHAR(500) NOT NULL,
	image_type VARCHAR(30),
	display_order SMALLINT NOT NULL,
	alt_text VARCHAR(300),
	approval_status VARCHAR(20) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_product_image PRIMARY KEY (product_image_id),
	CONSTRAINT ck_product_image_approval_status_allowed CHECK (approval_status IN ('PENDING', 'APPROVED', 'REJECTED')),
	CONSTRAINT ck_product_image_display_order_nonneg CHECK (display_order >= 0),
	CONSTRAINT fk_product_image_product_id_product FOREIGN KEY(product_id) REFERENCES exhibition.product (product_id)
);

CREATE TABLE exhibition.product_profile (
	product_profile_id UUID NOT NULL,
	product_id UUID NOT NULL,
	category_code VARCHAR(100),
	taste_json JSONB,
	aroma_json JSONB,
	usage_json JSONB,
	feature_json JSONB,
	consumer_score NUMERIC(5, 2) NOT NULL,
	buyer_score NUMERIC(5, 2) NOT NULL,
	current_version INTEGER NOT NULL,
	approval_status VARCHAR(20) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_product_profile PRIMARY KEY (product_profile_id),
	CONSTRAINT ck_product_profile_consumer_score_range CHECK (consumer_score >= 0 AND consumer_score <= 100),
	CONSTRAINT ck_product_profile_buyer_score_range CHECK (buyer_score >= 0 AND buyer_score <= 100),
	CONSTRAINT ck_product_profile_approval_status_allowed CHECK (approval_status IN ('DRAFT', 'SUBMITTED', 'APPROVED', 'REJECTED')),
	CONSTRAINT uq_product_profile_product_id UNIQUE (product_id),
	CONSTRAINT fk_product_profile_product_id_product FOREIGN KEY(product_id) REFERENCES exhibition.product (product_id)
);

CREATE TABLE exhibition.supply_capability (
	supply_capability_id UUID NOT NULL,
	exhibitor_id UUID NOT NULL,
	product_id UUID,
	monthly_capacity INTEGER,
	available_capacity INTEGER,
	lead_time_days INTEGER,
	supply_regions JSONB,
	logistics_methods JSONB,
	valid_from DATE,
	valid_until DATE,
	verification_status VARCHAR(20) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_supply_capability PRIMARY KEY (supply_capability_id),
	CONSTRAINT ck_supply_capability_monthly_capacity_nonneg CHECK (monthly_capacity IS NULL OR monthly_capacity >= 0),
	CONSTRAINT ck_supply_capability_available_capacity_nonneg CHECK (available_capacity IS NULL OR available_capacity >= 0),
	CONSTRAINT ck_supply_capability_lead_time_days_nonneg CHECK (lead_time_days IS NULL OR lead_time_days >= 0),
	CONSTRAINT ck_supply_capability_valid_period_order CHECK (valid_from IS NULL OR valid_until IS NULL OR valid_from <= valid_until),
	CONSTRAINT ck_supply_capability_verification_status_allowed CHECK (verification_status IN ('SELF_DECLARED', 'DOCUMENT_SUBMITTED', 'OPERATOR_REVIEWED', 'VERIFIED', 'EXPIRED', 'REJECTED')),
	CONSTRAINT fk_supply_capability_exhibitor_id_exhibitor FOREIGN KEY(exhibitor_id) REFERENCES exhibition.exhibitor (exhibitor_id),
	CONSTRAINT fk_supply_capability_product_id_product FOREIGN KEY(product_id) REFERENCES exhibition.product (product_id)
);

CREATE TABLE exhibition.booth_qr (
	booth_qr_id UUID NOT NULL,
	booth_id UUID NOT NULL,
	token_hmac BYTEA NOT NULL,
	valid_from TIMESTAMP WITH TIME ZONE,
	valid_until TIMESTAMP WITH TIME ZONE,
	status VARCHAR(20) NOT NULL,
	key_version INTEGER NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_booth_qr PRIMARY KEY (booth_qr_id),
	CONSTRAINT ck_booth_qr_status_allowed CHECK (status IN ('ACTIVE', 'REVOKED', 'EXPIRED')),
	CONSTRAINT ck_booth_qr_valid_period_order CHECK (valid_from IS NULL OR valid_until IS NULL OR valid_from < valid_until),
	CONSTRAINT ck_booth_qr_key_version_positive CHECK (key_version >= 1),
	CONSTRAINT fk_booth_qr_booth_id_booth FOREIGN KEY(booth_id) REFERENCES exhibition.booth (booth_id),
	CONSTRAINT uq_booth_qr_token_hmac UNIQUE (token_hmac)
);

CREATE TABLE exhibition.booth_status_history (
	booth_status_history_id UUID NOT NULL,
	booth_id UUID NOT NULL,
	previous_status VARCHAR(20),
	new_status VARCHAR(20) NOT NULL,
	changed_by_user_id UUID,
	reason_code VARCHAR(50),
	request_id UUID,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_booth_status_history PRIMARY KEY (booth_status_history_id),
	CONSTRAINT ck_booth_status_history_previous_status_allowed CHECK (previous_status IS NULL OR previous_status IN ('OPEN', 'PAUSED', 'CLOSED')),
	CONSTRAINT ck_booth_status_history_new_status_allowed CHECK (new_status IN ('OPEN', 'PAUSED', 'CLOSED')),
	CONSTRAINT fk_booth_status_history_booth_id_booth FOREIGN KEY(booth_id) REFERENCES exhibition.booth (booth_id),
	CONSTRAINT fk_booth_status_history_changed_by_user_id_user_account FOREIGN KEY(changed_by_user_id) REFERENCES profile.user_account (user_id)
);

CREATE INDEX ix_booth_status_history_booth_created ON exhibition.booth_status_history (booth_id, created_at);

CREATE TABLE exhibition.staff_topic (
	staff_id UUID NOT NULL,
	taxonomy_version_id UUID NOT NULL,
	concept_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_staff_topic PRIMARY KEY (staff_id, taxonomy_version_id, concept_id),
	CONSTRAINT fk_staff_topic_ontology_revision FOREIGN KEY(taxonomy_version_id, concept_id) REFERENCES ontology.concept_revision (taxonomy_version_id, concept_id),
	CONSTRAINT fk_staff_topic_staff_id_exhibitor_staff FOREIGN KEY(staff_id) REFERENCES exhibition.exhibitor_staff (staff_id)
);

CREATE TABLE exhibition.trade_condition (
	trade_condition_id UUID NOT NULL,
	participation_id UUID NOT NULL,
	event_product_id UUID,
	min_order_quantity INTEGER,
	max_order_quantity INTEGER,
	monthly_capacity INTEGER,
	wholesale_price_min_amount BIGINT,
	wholesale_price_max_amount BIGINT,
	currency CHAR(3) NOT NULL,
	oem_status VARCHAR(20) NOT NULL,
	private_label_status VARCHAR(20) NOT NULL,
	exclusive_distribution_considered BOOLEAN NOT NULL,
	export_status VARCHAR(20) NOT NULL,
	lead_time_days INTEGER,
	valid_from DATE,
	valid_until DATE,
	approval_status VARCHAR(20) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_trade_condition PRIMARY KEY (trade_condition_id),
	CONSTRAINT ck_trade_condition_min_order_quantity_nonneg CHECK (min_order_quantity IS NULL OR min_order_quantity >= 0),
	CONSTRAINT ck_trade_condition_max_order_quantity_nonneg CHECK (max_order_quantity IS NULL OR max_order_quantity >= 0),
	CONSTRAINT ck_trade_condition_order_quantity_order CHECK (min_order_quantity IS NULL OR max_order_quantity IS NULL OR min_order_quantity <= max_order_quantity),
	CONSTRAINT ck_trade_condition_monthly_capacity_nonneg CHECK (monthly_capacity IS NULL OR monthly_capacity >= 0),
	CONSTRAINT ck_trade_condition_wholesale_price_min_nonneg CHECK (wholesale_price_min_amount IS NULL OR wholesale_price_min_amount >= 0),
	CONSTRAINT ck_trade_condition_wholesale_price_max_nonneg CHECK (wholesale_price_max_amount IS NULL OR wholesale_price_max_amount >= 0),
	CONSTRAINT ck_trade_condition_wholesale_price_order CHECK (wholesale_price_min_amount IS NULL OR wholesale_price_max_amount IS NULL OR wholesale_price_min_amount <= wholesale_price_max_amount),
	CONSTRAINT ck_trade_condition_oem_status_allowed CHECK (oem_status IN ('YES', 'NO', 'CONDITIONAL', 'NEGOTIABLE', 'UNKNOWN')),
	CONSTRAINT ck_trade_condition_private_label_status_allowed CHECK (private_label_status IN ('YES', 'NO', 'CONDITIONAL', 'NEGOTIABLE', 'UNKNOWN')),
	CONSTRAINT ck_trade_condition_export_status_allowed CHECK (export_status IN ('YES', 'NO', 'CONDITIONAL', 'NEGOTIABLE', 'UNKNOWN')),
	CONSTRAINT ck_trade_condition_lead_time_days_nonneg CHECK (lead_time_days IS NULL OR lead_time_days >= 0),
	CONSTRAINT ck_trade_condition_valid_period_order CHECK (valid_from IS NULL OR valid_until IS NULL OR valid_from <= valid_until),
	CONSTRAINT ck_trade_condition_approval_status_allowed CHECK (approval_status IN ('DRAFT', 'APPROVED', 'REJECTED')),
	CONSTRAINT fk_trade_condition_participation_id_exhibitor_participation FOREIGN KEY(participation_id) REFERENCES exhibition.exhibitor_participation (participation_id),
	CONSTRAINT fk_trade_condition_event_product_id_event_product FOREIGN KEY(event_product_id) REFERENCES exhibition.event_product (event_product_id)
);

CREATE TABLE exhibition.trade_condition_term (
	trade_condition_term_id UUID NOT NULL,
	trade_condition_id UUID NOT NULL,
	term_type VARCHAR(20) NOT NULL,
	taxonomy_version_id UUID NOT NULL,
	concept_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_trade_condition_term PRIMARY KEY (trade_condition_term_id),
	CONSTRAINT fk_trade_condition_term_ontology_revision FOREIGN KEY(taxonomy_version_id, concept_id) REFERENCES ontology.concept_revision (taxonomy_version_id, concept_id),
	CONSTRAINT ck_trade_condition_term_term_type_allowed CHECK (term_type IN ('REGION', 'CHANNEL', 'COUNTRY')),
	CONSTRAINT uq_trade_condition_term UNIQUE (trade_condition_id, term_type, taxonomy_version_id, concept_id),
	CONSTRAINT fk_trade_condition_term_trade_condition_id_trade_condition FOREIGN KEY(trade_condition_id) REFERENCES exhibition.trade_condition (trade_condition_id)
);

ALTER TABLE profile.user_role
    ADD CONSTRAINT fk_user_role_exhibitor_boundary
    FOREIGN KEY (tenant_id, exhibitor_id)
    REFERENCES exhibition.exhibitor (tenant_id, exhibitor_id);

CREATE OR REPLACE FUNCTION exhibition.validate_event_product_owner()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM exhibition.exhibitor_participation participation
        JOIN exhibition.product product
          ON product.exhibitor_id = participation.exhibitor_id
        WHERE participation.participation_id = NEW.participation_id
          AND participation.tenant_id = NEW.tenant_id
          AND participation.event_id = NEW.event_id
          AND product.product_id = NEW.product_id
    ) THEN
        RAISE EXCEPTION
            'event product %, participation %, and product % do not share an exhibitor/event boundary',
            NEW.event_product_id, NEW.participation_id, NEW.product_id
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_event_product_owner_boundary
BEFORE INSERT OR UPDATE OF tenant_id, event_id, participation_id, product_id
ON exhibition.event_product
FOR EACH ROW EXECUTE FUNCTION exhibition.validate_event_product_owner();

CREATE OR REPLACE FUNCTION exhibition.validate_trade_condition_scope()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.event_product_id IS NOT NULL AND NOT EXISTS (
        SELECT 1
        FROM exhibition.event_product event_product
        WHERE event_product.event_product_id = NEW.event_product_id
          AND event_product.participation_id = NEW.participation_id
    ) THEN
        RAISE EXCEPTION
            'trade condition % references an event product outside participation %',
            NEW.trade_condition_id, NEW.participation_id
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_trade_condition_scope
BEFORE INSERT OR UPDATE OF participation_id, event_product_id
ON exhibition.trade_condition
FOR EACH ROW EXECUTE FUNCTION exhibition.validate_trade_condition_scope();

CREATE OR REPLACE FUNCTION exhibition.validate_supply_capability_owner()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.product_id IS NOT NULL AND NOT EXISTS (
        SELECT 1
        FROM exhibition.product product
        WHERE product.product_id = NEW.product_id
          AND product.exhibitor_id = NEW.exhibitor_id
    ) THEN
        RAISE EXCEPTION
            'supply capability % product does not belong to exhibitor %',
            NEW.supply_capability_id, NEW.exhibitor_id
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_supply_capability_owner
BEFORE INSERT OR UPDATE OF exhibitor_id, product_id
ON exhibition.supply_capability
FOR EACH ROW EXECUTE FUNCTION exhibition.validate_supply_capability_owner();

CREATE OR REPLACE FUNCTION exhibition.validate_product_profile_category_code()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.category_code IS NOT NULL AND NOT EXISTS (
        SELECT 1
        FROM exhibition.product product
        JOIN ontology.concept concept
          ON concept.concept_id = product.category_concept_id
        WHERE product.product_id = NEW.product_id
          AND concept.concept_code = NEW.category_code
    ) THEN
        RAISE EXCEPTION
            'product profile % category code does not match product taxonomy',
            NEW.product_profile_id
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_product_profile_category_code
BEFORE INSERT OR UPDATE OF product_id, category_code
ON exhibition.product_profile
FOR EACH ROW EXECUTE FUNCTION exhibition.validate_product_profile_category_code();

CREATE OR REPLACE FUNCTION exhibition.validate_supply_attribute_target()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.object_type = 'EXHIBITOR' THEN
        IF NOT EXISTS (
            SELECT 1 FROM exhibition.exhibitor WHERE exhibitor_id = NEW.object_id
        ) THEN
            RAISE EXCEPTION 'unknown exhibitor attribute target %', NEW.object_id
                USING ERRCODE = '23503';
        END IF;
    ELSIF NEW.object_type = 'PRODUCT' THEN
        IF NOT EXISTS (
            SELECT 1 FROM exhibition.product WHERE product_id = NEW.object_id
        ) THEN
            RAISE EXCEPTION 'unknown product attribute target %', NEW.object_id
                USING ERRCODE = '23503';
        END IF;
    ELSIF NEW.object_type = 'TRADE_CONDITION' THEN
        IF NOT EXISTS (
            SELECT 1 FROM exhibition.trade_condition WHERE trade_condition_id = NEW.object_id
        ) THEN
            RAISE EXCEPTION 'unknown trade-condition attribute target %', NEW.object_id
                USING ERRCODE = '23503';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_supply_attribute_target
BEFORE INSERT OR UPDATE OF object_type, object_id
ON exhibition.profile_attribute
FOR EACH ROW EXECUTE FUNCTION exhibition.validate_supply_attribute_target();

CREATE OR REPLACE FUNCTION exhibition.validate_user_role_scope()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    selected_role_code VARCHAR(30);
BEGIN
    SELECT role_code INTO selected_role_code
    FROM profile.role
    WHERE role_id = NEW.role_id;

    IF selected_role_code = 'EXHIBITOR' AND NEW.exhibitor_id IS NULL THEN
        RAISE EXCEPTION 'EXHIBITOR role requires exhibitor_id' USING ERRCODE = '23514';
    END IF;
    IF selected_role_code = 'OPERATOR' AND NEW.event_id IS NULL THEN
        RAISE EXCEPTION 'OPERATOR role requires event_id' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_user_role_scope
BEFORE INSERT OR UPDATE OF role_id, event_id, exhibitor_id
ON profile.user_role
FOR EACH ROW EXECUTE FUNCTION exhibition.validate_user_role_scope();

COMMIT;
