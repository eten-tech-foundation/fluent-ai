--
-- PostgreSQL database dump
--


-- Dumped from database version 16.12
-- Dumped by pg_dump version 18.3 (Ubuntu 18.3-1.pgdg22.04+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
--

CREATE SCHEMA IF NOT EXISTS public;



--
--

COMMENT ON SCHEMA public IS 'standard public schema';


--
-- Name: assignment_role; Type: TYPE; Schema: public; Owner: scribedb_dev
--

CREATE TYPE public.assignment_role AS ENUM (
    'drafter',
    'peer_checker'
);


ALTER TYPE public.assignment_role OWNER TO postgres;

--
-- Name: chapter_status; Type: TYPE; Schema: public; Owner: scribedb_dev
--

CREATE TYPE public.chapter_status AS ENUM (
    'not_started',
    'draft',
    'peer_check',
    'community_review',
    'linguist_check',
    'theological_check',
    'consultant_check',
    'complete'
);


ALTER TYPE public.chapter_status OWNER TO postgres;

--
-- Name: project_assignment_status; Type: TYPE; Schema: public; Owner: scribedb_dev
--

CREATE TYPE public.project_assignment_status AS ENUM (
    'active',
    'not_assigned'
);


ALTER TYPE public.project_assignment_status OWNER TO postgres;

--
-- Name: project_status; Type: TYPE; Schema: public; Owner: scribedb_dev
--

CREATE TYPE public.project_status AS ENUM (
    'not_started',
    'in_progress',
    'completed'
);


ALTER TYPE public.project_status OWNER TO postgres;

--
-- Name: script_direction; Type: TYPE; Schema: public; Owner: scribedb_dev
--

CREATE TYPE public.script_direction AS ENUM (
    'ltr',
    'rtl'
);


ALTER TYPE public.script_direction OWNER TO postgres;

--
-- Name: user_status; Type: TYPE; Schema: public; Owner: scribedb_dev
--

CREATE TYPE public.user_status AS ENUM (
    'invited',
    'verified',
    'inactive'
);


ALTER TYPE public.user_status OWNER TO postgres;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: active_chapter_editors; Type: TABLE; Schema: public; Owner: scribedb_admin
--

CREATE TABLE public.active_chapter_editors (
    chapter_assignment_id integer NOT NULL,
    user_id integer NOT NULL,
    started_at timestamp without time zone DEFAULT now() NOT NULL,
    last_heartbeat timestamp without time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.active_chapter_editors OWNER TO postgres;

--
-- Name: bible_books; Type: TABLE; Schema: public; Owner: scribedb_dev
--

CREATE TABLE public.bible_books (
    bible_id integer NOT NULL,
    book_id integer NOT NULL,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.bible_books OWNER TO postgres;

--
-- Name: bible_texts; Type: TABLE; Schema: public; Owner: scribedb_dev
--

CREATE TABLE public.bible_texts (
    id integer NOT NULL,
    bible_id integer NOT NULL,
    book_id integer NOT NULL,
    chapter_number integer NOT NULL,
    verse_number integer NOT NULL,
    text character varying NOT NULL,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.bible_texts OWNER TO postgres;

--
-- Name: bible_texts_id_seq; Type: SEQUENCE; Schema: public; Owner: scribedb_dev
--

CREATE SEQUENCE public.bible_texts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.bible_texts_id_seq OWNER TO postgres;

--
-- Name: bible_texts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: scribedb_dev
--

ALTER SEQUENCE public.bible_texts_id_seq OWNED BY public.bible_texts.id;


--
-- Name: bibles; Type: TABLE; Schema: public; Owner: scribedb_dev
--

CREATE TABLE public.bibles (
    id integer NOT NULL,
    language_id integer NOT NULL,
    name character varying(255) NOT NULL,
    abbreviation character varying(50) NOT NULL,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.bibles OWNER TO postgres;

--
-- Name: bibles_id_seq; Type: SEQUENCE; Schema: public; Owner: scribedb_dev
--

CREATE SEQUENCE public.bibles_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.bibles_id_seq OWNER TO postgres;

--
-- Name: bibles_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: scribedb_dev
--

ALTER SEQUENCE public.bibles_id_seq OWNED BY public.bibles.id;


--
-- Name: books; Type: TABLE; Schema: public; Owner: scribedb_dev
--

CREATE TABLE public.books (
    id integer NOT NULL,
    code character varying(50) NOT NULL,
    eng_display_name character varying(255) NOT NULL
);


ALTER TABLE public.books OWNER TO postgres;

--
-- Name: books_id_seq; Type: SEQUENCE; Schema: public; Owner: scribedb_dev
--

CREATE SEQUENCE public.books_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.books_id_seq OWNER TO postgres;

--
-- Name: books_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: scribedb_dev
--

ALTER SEQUENCE public.books_id_seq OWNED BY public.books.id;


--
-- Name: chapter_assignment_assigned_user_history; Type: TABLE; Schema: public; Owner: scribedb_dev
--

CREATE TABLE public.chapter_assignment_assigned_user_history (
    id integer NOT NULL,
    chapter_assignment_id integer NOT NULL,
    assigned_user_id integer NOT NULL,
    role public.assignment_role NOT NULL,
    status public.chapter_status NOT NULL,
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.chapter_assignment_assigned_user_history OWNER TO postgres;

--
-- Name: chapter_assignment_assigned_user_history_id_seq; Type: SEQUENCE; Schema: public; Owner: scribedb_dev
--

CREATE SEQUENCE public.chapter_assignment_assigned_user_history_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.chapter_assignment_assigned_user_history_id_seq OWNER TO postgres;

--
-- Name: chapter_assignment_assigned_user_history_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: scribedb_dev
--

ALTER SEQUENCE public.chapter_assignment_assigned_user_history_id_seq OWNED BY public.chapter_assignment_assigned_user_history.id;


--
-- Name: chapter_assignment_snapshots; Type: TABLE; Schema: public; Owner: scribedb_dev
--

CREATE TABLE public.chapter_assignment_snapshots (
    id integer NOT NULL,
    chapter_assignment_id integer NOT NULL,
    status public.chapter_status NOT NULL,
    assigned_user_id integer,
    content json NOT NULL,
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.chapter_assignment_snapshots OWNER TO postgres;

--
-- Name: chapter_assignment_snapshots_id_seq; Type: SEQUENCE; Schema: public; Owner: scribedb_dev
--

CREATE SEQUENCE public.chapter_assignment_snapshots_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.chapter_assignment_snapshots_id_seq OWNER TO postgres;

--
-- Name: chapter_assignment_snapshots_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: scribedb_dev
--

ALTER SEQUENCE public.chapter_assignment_snapshots_id_seq OWNED BY public.chapter_assignment_snapshots.id;


--
-- Name: chapter_assignment_status_history; Type: TABLE; Schema: public; Owner: scribedb_dev
--

CREATE TABLE public.chapter_assignment_status_history (
    id integer NOT NULL,
    chapter_assignment_id integer NOT NULL,
    status public.chapter_status NOT NULL,
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.chapter_assignment_status_history OWNER TO postgres;

--
-- Name: chapter_assignment_status_history_id_seq; Type: SEQUENCE; Schema: public; Owner: scribedb_dev
--

CREATE SEQUENCE public.chapter_assignment_status_history_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.chapter_assignment_status_history_id_seq OWNER TO postgres;

--
-- Name: chapter_assignment_status_history_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: scribedb_dev
--

ALTER SEQUENCE public.chapter_assignment_status_history_id_seq OWNED BY public.chapter_assignment_status_history.id;


--
-- Name: chapter_assignments; Type: TABLE; Schema: public; Owner: scribedb_dev
--

CREATE TABLE public.chapter_assignments (
    id integer NOT NULL,
    project_unit_id integer NOT NULL,
    bible_id integer NOT NULL,
    book_id integer NOT NULL,
    chapter_number integer NOT NULL,
    assigned_user_id integer,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    submitted_time timestamp without time zone,
    peer_checker_id integer,
    chapter_status public.chapter_status DEFAULT 'not_started'::public.chapter_status NOT NULL
);


ALTER TABLE public.chapter_assignments OWNER TO postgres;

--
-- Name: chapter_assignments_id_seq; Type: SEQUENCE; Schema: public; Owner: scribedb_dev
--

CREATE SEQUENCE public.chapter_assignments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.chapter_assignments_id_seq OWNER TO postgres;

--
-- Name: chapter_assignments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: scribedb_dev
--

ALTER SEQUENCE public.chapter_assignments_id_seq OWNED BY public.chapter_assignments.id;


--
-- Name: languages; Type: TABLE; Schema: public; Owner: scribedb_dev
--

CREATE TABLE public.languages (
    id integer NOT NULL,
    lang_name character varying(100) NOT NULL,
    lang_name_localized character varying(100),
    lang_code_iso_639_3 character varying(3),
    script_direction public.script_direction DEFAULT 'ltr'::public.script_direction,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.languages OWNER TO postgres;

--
-- Name: languages_id_seq; Type: SEQUENCE; Schema: public; Owner: scribedb_dev
--

CREATE SEQUENCE public.languages_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.languages_id_seq OWNER TO postgres;

--
-- Name: languages_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: scribedb_dev
--

ALTER SEQUENCE public.languages_id_seq OWNED BY public.languages.id;


--
-- Name: organizations; Type: TABLE; Schema: public; Owner: scribedb_dev
--

CREATE TABLE public.organizations (
    id integer NOT NULL,
    name character varying(100) NOT NULL,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.organizations OWNER TO postgres;

--
-- Name: organizations_id_seq; Type: SEQUENCE; Schema: public; Owner: scribedb_dev
--

CREATE SEQUENCE public.organizations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.organizations_id_seq OWNER TO postgres;

--
-- Name: organizations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: scribedb_dev
--

ALTER SEQUENCE public.organizations_id_seq OWNED BY public.organizations.id;


--
-- Name: permissions; Type: TABLE; Schema: public; Owner: scribedb_dev
--

CREATE TABLE public.permissions (
    id integer NOT NULL,
    name character varying(100) NOT NULL,
    description character varying(255),
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.permissions OWNER TO postgres;

--
-- Name: permissions_id_seq; Type: SEQUENCE; Schema: public; Owner: scribedb_dev
--

CREATE SEQUENCE public.permissions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.permissions_id_seq OWNER TO postgres;

--
-- Name: permissions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: scribedb_dev
--

ALTER SEQUENCE public.permissions_id_seq OWNED BY public.permissions.id;


--
-- Name: project_unit_bible_books; Type: TABLE; Schema: public; Owner: scribedb_dev
--

CREATE TABLE public.project_unit_bible_books (
    project_unit_id integer NOT NULL,
    bible_id integer NOT NULL,
    book_id integer NOT NULL,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.project_unit_bible_books OWNER TO postgres;

--
-- Name: project_units; Type: TABLE; Schema: public; Owner: scribedb_dev
--

CREATE TABLE public.project_units (
    id integer NOT NULL,
    project_id integer NOT NULL,
    status public.project_status DEFAULT 'not_started'::public.project_status NOT NULL,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.project_units OWNER TO postgres;

--
-- Name: project_units_id_seq; Type: SEQUENCE; Schema: public; Owner: scribedb_dev
--

CREATE SEQUENCE public.project_units_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.project_units_id_seq OWNER TO postgres;

--
-- Name: project_units_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: scribedb_dev
--

ALTER SEQUENCE public.project_units_id_seq OWNED BY public.project_units.id;


--
-- Name: project_users; Type: TABLE; Schema: public; Owner: scribedb_dev
--

CREATE TABLE public.project_users (
    project_id integer NOT NULL,
    user_id integer NOT NULL,
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.project_users OWNER TO postgres;

--
-- Name: projects; Type: TABLE; Schema: public; Owner: scribedb_dev
--

CREATE TABLE public.projects (
    id integer NOT NULL,
    name character varying(255) NOT NULL,
    source_language integer NOT NULL,
    target_language integer NOT NULL,
    is_active boolean DEFAULT true,
    created_by integer,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    organization integer NOT NULL,
    status public.project_assignment_status DEFAULT 'not_assigned'::public.project_assignment_status NOT NULL
);


ALTER TABLE public.projects OWNER TO postgres;

--
-- Name: projects_id_seq; Type: SEQUENCE; Schema: public; Owner: scribedb_dev
--

CREATE SEQUENCE public.projects_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.projects_id_seq OWNER TO postgres;

--
-- Name: projects_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: scribedb_dev
--

ALTER SEQUENCE public.projects_id_seq OWNED BY public.projects.id;


--
-- Name: role_permissions; Type: TABLE; Schema: public; Owner: scribedb_dev
--

CREATE TABLE public.role_permissions (
    role_id integer NOT NULL,
    permission_id integer NOT NULL,
    updated_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.role_permissions OWNER TO postgres;

--
-- Name: roles; Type: TABLE; Schema: public; Owner: scribedb_dev
--

CREATE TABLE public.roles (
    id integer NOT NULL,
    name character varying(255) NOT NULL,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.roles OWNER TO postgres;

--
-- Name: roles_id_seq; Type: SEQUENCE; Schema: public; Owner: scribedb_dev
--

CREATE SEQUENCE public.roles_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.roles_id_seq OWNER TO postgres;

--
-- Name: roles_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: scribedb_dev
--

ALTER SEQUENCE public.roles_id_seq OWNED BY public.roles.id;


--
-- Name: translated_verses; Type: TABLE; Schema: public; Owner: scribedb_dev
--

CREATE TABLE public.translated_verses (
    id integer NOT NULL,
    project_unit_id integer NOT NULL,
    content character varying NOT NULL,
    bible_text_id integer NOT NULL,
    assigned_user_id integer,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.translated_verses OWNER TO postgres;

--
-- Name: translated_verses_id_seq; Type: SEQUENCE; Schema: public; Owner: scribedb_dev
--

CREATE SEQUENCE public.translated_verses_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.translated_verses_id_seq OWNER TO postgres;

--
-- Name: translated_verses_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: scribedb_dev
--

ALTER SEQUENCE public.translated_verses_id_seq OWNED BY public.translated_verses.id;


--
-- Name: user_chapter_assignment_editor_state; Type: TABLE; Schema: public; Owner: scribedb_dev
--

CREATE TABLE public.user_chapter_assignment_editor_state (
    user_id integer NOT NULL,
    chapter_assignment_id integer NOT NULL,
    resources jsonb,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.user_chapter_assignment_editor_state OWNER TO postgres;

--
-- Name: users; Type: TABLE; Schema: public; Owner: scribedb_dev
--

CREATE TABLE public.users (
    id integer NOT NULL,
    username character varying(100) NOT NULL,
    email character varying(255) NOT NULL,
    first_name character varying(100),
    last_name character varying(100),
    role integer NOT NULL,
    organization integer NOT NULL,
    created_by integer,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    status public.user_status DEFAULT 'invited'::public.user_status NOT NULL
);


ALTER TABLE public.users OWNER TO postgres;

--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: scribedb_dev
--

CREATE SEQUENCE public.users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.users_id_seq OWNER TO postgres;

--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: scribedb_dev
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- Name: bible_texts id; Type: DEFAULT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.bible_texts ALTER COLUMN id SET DEFAULT nextval('public.bible_texts_id_seq'::regclass);


--
-- Name: bibles id; Type: DEFAULT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.bibles ALTER COLUMN id SET DEFAULT nextval('public.bibles_id_seq'::regclass);


--
-- Name: books id; Type: DEFAULT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.books ALTER COLUMN id SET DEFAULT nextval('public.books_id_seq'::regclass);


--
-- Name: chapter_assignment_assigned_user_history id; Type: DEFAULT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.chapter_assignment_assigned_user_history ALTER COLUMN id SET DEFAULT nextval('public.chapter_assignment_assigned_user_history_id_seq'::regclass);


--
-- Name: chapter_assignment_snapshots id; Type: DEFAULT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.chapter_assignment_snapshots ALTER COLUMN id SET DEFAULT nextval('public.chapter_assignment_snapshots_id_seq'::regclass);


--
-- Name: chapter_assignment_status_history id; Type: DEFAULT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.chapter_assignment_status_history ALTER COLUMN id SET DEFAULT nextval('public.chapter_assignment_status_history_id_seq'::regclass);


--
-- Name: chapter_assignments id; Type: DEFAULT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.chapter_assignments ALTER COLUMN id SET DEFAULT nextval('public.chapter_assignments_id_seq'::regclass);


--
-- Name: languages id; Type: DEFAULT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.languages ALTER COLUMN id SET DEFAULT nextval('public.languages_id_seq'::regclass);


--
-- Name: organizations id; Type: DEFAULT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.organizations ALTER COLUMN id SET DEFAULT nextval('public.organizations_id_seq'::regclass);


--
-- Name: permissions id; Type: DEFAULT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.permissions ALTER COLUMN id SET DEFAULT nextval('public.permissions_id_seq'::regclass);


--
-- Name: project_units id; Type: DEFAULT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.project_units ALTER COLUMN id SET DEFAULT nextval('public.project_units_id_seq'::regclass);


--
-- Name: projects id; Type: DEFAULT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.projects ALTER COLUMN id SET DEFAULT nextval('public.projects_id_seq'::regclass);


--
-- Name: roles id; Type: DEFAULT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.roles ALTER COLUMN id SET DEFAULT nextval('public.roles_id_seq'::regclass);


--
-- Name: translated_verses id; Type: DEFAULT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.translated_verses ALTER COLUMN id SET DEFAULT nextval('public.translated_verses_id_seq'::regclass);


--
-- Name: users id; Type: DEFAULT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- Name: active_chapter_editors active_chapter_editors_chapter_assignment_id_user_id_pk; Type: CONSTRAINT; Schema: public; Owner: scribedb_admin
--

ALTER TABLE ONLY public.active_chapter_editors
    ADD CONSTRAINT active_chapter_editors_chapter_assignment_id_user_id_pk PRIMARY KEY (chapter_assignment_id, user_id);


--
-- Name: bible_texts bible_texts_pkey; Type: CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.bible_texts
    ADD CONSTRAINT bible_texts_pkey PRIMARY KEY (id);


--
-- Name: bibles bibles_abbreviation_unique; Type: CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.bibles
    ADD CONSTRAINT bibles_abbreviation_unique UNIQUE (abbreviation);


--
-- Name: bibles bibles_name_unique; Type: CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.bibles
    ADD CONSTRAINT bibles_name_unique UNIQUE (name);


--
-- Name: bibles bibles_pkey; Type: CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.bibles
    ADD CONSTRAINT bibles_pkey PRIMARY KEY (id);


--
-- Name: books books_pkey; Type: CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.books
    ADD CONSTRAINT books_pkey PRIMARY KEY (id);


--
-- Name: chapter_assignment_assigned_user_history chapter_assignment_assigned_user_history_pkey; Type: CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.chapter_assignment_assigned_user_history
    ADD CONSTRAINT chapter_assignment_assigned_user_history_pkey PRIMARY KEY (id);


--
-- Name: chapter_assignment_snapshots chapter_assignment_snapshots_pkey; Type: CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.chapter_assignment_snapshots
    ADD CONSTRAINT chapter_assignment_snapshots_pkey PRIMARY KEY (id);


--
-- Name: chapter_assignment_status_history chapter_assignment_status_history_pkey; Type: CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.chapter_assignment_status_history
    ADD CONSTRAINT chapter_assignment_status_history_pkey PRIMARY KEY (id);


--
-- Name: chapter_assignments chapter_assignments_pkey; Type: CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.chapter_assignments
    ADD CONSTRAINT chapter_assignments_pkey PRIMARY KEY (id);


--
-- Name: languages languages_pkey; Type: CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.languages
    ADD CONSTRAINT languages_pkey PRIMARY KEY (id);


--
-- Name: organizations organizations_name_unique; Type: CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.organizations
    ADD CONSTRAINT organizations_name_unique UNIQUE (name);


--
-- Name: organizations organizations_pkey; Type: CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.organizations
    ADD CONSTRAINT organizations_pkey PRIMARY KEY (id);


--
-- Name: permissions permissions_name_unique; Type: CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.permissions
    ADD CONSTRAINT permissions_name_unique UNIQUE (name);


--
-- Name: permissions permissions_pkey; Type: CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.permissions
    ADD CONSTRAINT permissions_pkey PRIMARY KEY (id);


--
-- Name: project_units project_units_pkey; Type: CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.project_units
    ADD CONSTRAINT project_units_pkey PRIMARY KEY (id);


--
-- Name: project_users project_users_project_id_user_id_pk; Type: CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.project_users
    ADD CONSTRAINT project_users_project_id_user_id_pk PRIMARY KEY (project_id, user_id);


--
-- Name: projects projects_pkey; Type: CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_pkey PRIMARY KEY (id);


--
-- Name: role_permissions role_permissions_role_id_permission_id_pk; Type: CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT role_permissions_role_id_permission_id_pk PRIMARY KEY (role_id, permission_id);


--
-- Name: roles roles_name_unique; Type: CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_name_unique UNIQUE (name);


--
-- Name: roles roles_pkey; Type: CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_pkey PRIMARY KEY (id);


--
-- Name: translated_verses translated_verses_pkey; Type: CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.translated_verses
    ADD CONSTRAINT translated_verses_pkey PRIMARY KEY (id);


--
-- Name: users users_email_unique; Type: CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_email_unique UNIQUE (email);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: users users_username_unique; Type: CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_username_unique UNIQUE (username);


--
-- Name: idx_active_editors_chapter; Type: INDEX; Schema: public; Owner: scribedb_admin
--

CREATE INDEX idx_active_editors_chapter ON public.active_chapter_editors USING btree (chapter_assignment_id);


--
-- Name: idx_bible_texts_bible_book_chapter; Type: INDEX; Schema: public; Owner: scribedb_dev
--

CREATE INDEX idx_bible_texts_bible_book_chapter ON public.bible_texts USING btree (bible_id, book_id, chapter_number);


--
-- Name: idx_bible_texts_bible_book_chapter_verse; Type: INDEX; Schema: public; Owner: scribedb_dev
--

CREATE INDEX idx_bible_texts_bible_book_chapter_verse ON public.bible_texts USING btree (bible_id, book_id, chapter_number, verse_number);


--
-- Name: idx_ca_snapshots_assignment; Type: INDEX; Schema: public; Owner: scribedb_dev
--

CREATE INDEX idx_ca_snapshots_assignment ON public.chapter_assignment_snapshots USING btree (chapter_assignment_id);


--
-- Name: idx_ca_snapshots_user; Type: INDEX; Schema: public; Owner: scribedb_dev
--

CREATE INDEX idx_ca_snapshots_user ON public.chapter_assignment_snapshots USING btree (assigned_user_id);


--
-- Name: idx_ca_status_history_assignment; Type: INDEX; Schema: public; Owner: scribedb_dev
--

CREATE INDEX idx_ca_status_history_assignment ON public.chapter_assignment_status_history USING btree (chapter_assignment_id);


--
-- Name: idx_ca_user_history_assignment; Type: INDEX; Schema: public; Owner: scribedb_dev
--

CREATE INDEX idx_ca_user_history_assignment ON public.chapter_assignment_assigned_user_history USING btree (chapter_assignment_id);


--
-- Name: idx_ca_user_history_user; Type: INDEX; Schema: public; Owner: scribedb_dev
--

CREATE INDEX idx_ca_user_history_user ON public.chapter_assignment_assigned_user_history USING btree (assigned_user_id);


--
-- Name: idx_chapter_assignments_assigned_user; Type: INDEX; Schema: public; Owner: scribedb_dev
--

CREATE INDEX idx_chapter_assignments_assigned_user ON public.chapter_assignments USING btree (assigned_user_id);


--
-- Name: idx_chapter_assignments_peer_checker_status; Type: INDEX; Schema: public; Owner: scribedb_dev
--

CREATE INDEX idx_chapter_assignments_peer_checker_status ON public.chapter_assignments USING btree (peer_checker_id, chapter_status);


--
-- Name: idx_chapter_assignments_project_unit; Type: INDEX; Schema: public; Owner: scribedb_dev
--

CREATE INDEX idx_chapter_assignments_project_unit ON public.chapter_assignments USING btree (project_unit_id);


--
-- Name: idx_project_users_project; Type: INDEX; Schema: public; Owner: scribedb_dev
--

CREATE INDEX idx_project_users_project ON public.project_users USING btree (project_id);


--
-- Name: idx_project_users_user; Type: INDEX; Schema: public; Owner: scribedb_dev
--

CREATE INDEX idx_project_users_user ON public.project_users USING btree (user_id);


--
-- Name: idx_role_permissions_role; Type: INDEX; Schema: public; Owner: scribedb_dev
--

CREATE INDEX idx_role_permissions_role ON public.role_permissions USING btree (role_id);


--
-- Name: uq_chapter_assignment_per_chapter; Type: INDEX; Schema: public; Owner: scribedb_dev
--

CREATE UNIQUE INDEX uq_chapter_assignment_per_chapter ON public.chapter_assignments USING btree (project_unit_id, bible_id, book_id, chapter_number);


--
-- Name: uq_translated_verse_per_bible_text; Type: INDEX; Schema: public; Owner: scribedb_dev
--

CREATE UNIQUE INDEX uq_translated_verse_per_bible_text ON public.translated_verses USING btree (project_unit_id, bible_text_id);


--
-- Name: uq_user_chapter_assignment_editor_state; Type: INDEX; Schema: public; Owner: scribedb_dev
--

CREATE UNIQUE INDEX uq_user_chapter_assignment_editor_state ON public.user_chapter_assignment_editor_state USING btree (user_id, chapter_assignment_id);


--
-- Name: active_chapter_editors active_chapter_editors_chapter_assignment_id_chapter_assignment; Type: FK CONSTRAINT; Schema: public; Owner: scribedb_admin
--

ALTER TABLE ONLY public.active_chapter_editors
    ADD CONSTRAINT active_chapter_editors_chapter_assignment_id_chapter_assignment FOREIGN KEY (chapter_assignment_id) REFERENCES public.chapter_assignments(id) ON DELETE CASCADE;


--
-- Name: active_chapter_editors active_chapter_editors_user_id_users_id_fk; Type: FK CONSTRAINT; Schema: public; Owner: scribedb_admin
--

ALTER TABLE ONLY public.active_chapter_editors
    ADD CONSTRAINT active_chapter_editors_user_id_users_id_fk FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: bible_books bible_books_bible_id_bibles_id_fk; Type: FK CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.bible_books
    ADD CONSTRAINT bible_books_bible_id_bibles_id_fk FOREIGN KEY (bible_id) REFERENCES public.bibles(id);


--
-- Name: bible_books bible_books_book_id_books_id_fk; Type: FK CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.bible_books
    ADD CONSTRAINT bible_books_book_id_books_id_fk FOREIGN KEY (book_id) REFERENCES public.books(id);


--
-- Name: bible_texts bible_texts_bible_id_bibles_id_fk; Type: FK CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.bible_texts
    ADD CONSTRAINT bible_texts_bible_id_bibles_id_fk FOREIGN KEY (bible_id) REFERENCES public.bibles(id);


--
-- Name: bible_texts bible_texts_book_id_books_id_fk; Type: FK CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.bible_texts
    ADD CONSTRAINT bible_texts_book_id_books_id_fk FOREIGN KEY (book_id) REFERENCES public.books(id);


--
-- Name: bibles bibles_language_id_languages_id_fk; Type: FK CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.bibles
    ADD CONSTRAINT bibles_language_id_languages_id_fk FOREIGN KEY (language_id) REFERENCES public.languages(id);


--
-- Name: chapter_assignment_assigned_user_history chapter_assignment_assigned_user_history_assigned_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.chapter_assignment_assigned_user_history
    ADD CONSTRAINT chapter_assignment_assigned_user_history_assigned_user_id_users FOREIGN KEY (assigned_user_id) REFERENCES public.users(id);


--
-- Name: chapter_assignment_assigned_user_history chapter_assignment_assigned_user_history_chapter_assignment_id_; Type: FK CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.chapter_assignment_assigned_user_history
    ADD CONSTRAINT chapter_assignment_assigned_user_history_chapter_assignment_id_ FOREIGN KEY (chapter_assignment_id) REFERENCES public.chapter_assignments(id) ON DELETE CASCADE;


--
-- Name: chapter_assignment_snapshots chapter_assignment_snapshots_assigned_user_id_users_id_fk; Type: FK CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.chapter_assignment_snapshots
    ADD CONSTRAINT chapter_assignment_snapshots_assigned_user_id_users_id_fk FOREIGN KEY (assigned_user_id) REFERENCES public.users(id);


--
-- Name: chapter_assignment_snapshots chapter_assignment_snapshots_chapter_assignment_id_chapter_assi; Type: FK CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.chapter_assignment_snapshots
    ADD CONSTRAINT chapter_assignment_snapshots_chapter_assignment_id_chapter_assi FOREIGN KEY (chapter_assignment_id) REFERENCES public.chapter_assignments(id) ON DELETE CASCADE;


--
-- Name: chapter_assignment_status_history chapter_assignment_status_history_chapter_assignment_id_chapter; Type: FK CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.chapter_assignment_status_history
    ADD CONSTRAINT chapter_assignment_status_history_chapter_assignment_id_chapter FOREIGN KEY (chapter_assignment_id) REFERENCES public.chapter_assignments(id) ON DELETE CASCADE;


--
-- Name: chapter_assignments chapter_assignments_assigned_user_id_users_id_fk; Type: FK CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.chapter_assignments
    ADD CONSTRAINT chapter_assignments_assigned_user_id_users_id_fk FOREIGN KEY (assigned_user_id) REFERENCES public.users(id);


--
-- Name: chapter_assignments chapter_assignments_bible_id_bibles_id_fk; Type: FK CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.chapter_assignments
    ADD CONSTRAINT chapter_assignments_bible_id_bibles_id_fk FOREIGN KEY (bible_id) REFERENCES public.bibles(id);


--
-- Name: chapter_assignments chapter_assignments_book_id_books_id_fk; Type: FK CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.chapter_assignments
    ADD CONSTRAINT chapter_assignments_book_id_books_id_fk FOREIGN KEY (book_id) REFERENCES public.books(id);


--
-- Name: chapter_assignments chapter_assignments_peer_checker_id_users_id_fk; Type: FK CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.chapter_assignments
    ADD CONSTRAINT chapter_assignments_peer_checker_id_users_id_fk FOREIGN KEY (peer_checker_id) REFERENCES public.users(id);


--
-- Name: chapter_assignments chapter_assignments_project_unit_id_project_units_id_fk; Type: FK CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.chapter_assignments
    ADD CONSTRAINT chapter_assignments_project_unit_id_project_units_id_fk FOREIGN KEY (project_unit_id) REFERENCES public.project_units(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: project_unit_bible_books project_unit_bible_books_bible_id_bibles_id_fk; Type: FK CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.project_unit_bible_books
    ADD CONSTRAINT project_unit_bible_books_bible_id_bibles_id_fk FOREIGN KEY (bible_id) REFERENCES public.bibles(id);


--
-- Name: project_unit_bible_books project_unit_bible_books_book_id_books_id_fk; Type: FK CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.project_unit_bible_books
    ADD CONSTRAINT project_unit_bible_books_book_id_books_id_fk FOREIGN KEY (book_id) REFERENCES public.books(id);


--
-- Name: project_unit_bible_books project_unit_bible_books_project_unit_id_project_units_id_fk; Type: FK CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.project_unit_bible_books
    ADD CONSTRAINT project_unit_bible_books_project_unit_id_project_units_id_fk FOREIGN KEY (project_unit_id) REFERENCES public.project_units(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: project_units project_units_project_id_projects_id_fk; Type: FK CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.project_units
    ADD CONSTRAINT project_units_project_id_projects_id_fk FOREIGN KEY (project_id) REFERENCES public.projects(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: project_users project_users_project_id_projects_id_fk; Type: FK CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.project_users
    ADD CONSTRAINT project_users_project_id_projects_id_fk FOREIGN KEY (project_id) REFERENCES public.projects(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: project_users project_users_user_id_users_id_fk; Type: FK CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.project_users
    ADD CONSTRAINT project_users_user_id_users_id_fk FOREIGN KEY (user_id) REFERENCES public.users(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: projects projects_created_by_users_id_fk; Type: FK CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_created_by_users_id_fk FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: projects projects_organization_organizations_id_fk; Type: FK CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_organization_organizations_id_fk FOREIGN KEY (organization) REFERENCES public.organizations(id);


--
-- Name: projects projects_source_language_languages_id_fk; Type: FK CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_source_language_languages_id_fk FOREIGN KEY (source_language) REFERENCES public.languages(id);


--
-- Name: projects projects_target_language_languages_id_fk; Type: FK CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_target_language_languages_id_fk FOREIGN KEY (target_language) REFERENCES public.languages(id);


--
-- Name: role_permissions role_permissions_permission_id_permissions_id_fk; Type: FK CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT role_permissions_permission_id_permissions_id_fk FOREIGN KEY (permission_id) REFERENCES public.permissions(id) ON DELETE CASCADE;


--
-- Name: role_permissions role_permissions_role_id_roles_id_fk; Type: FK CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT role_permissions_role_id_roles_id_fk FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE CASCADE;


--
-- Name: translated_verses translated_verses_assigned_user_id_users_id_fk; Type: FK CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.translated_verses
    ADD CONSTRAINT translated_verses_assigned_user_id_users_id_fk FOREIGN KEY (assigned_user_id) REFERENCES public.users(id);


--
-- Name: translated_verses translated_verses_bible_text_id_bible_texts_id_fk; Type: FK CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.translated_verses
    ADD CONSTRAINT translated_verses_bible_text_id_bible_texts_id_fk FOREIGN KEY (bible_text_id) REFERENCES public.bible_texts(id);


--
-- Name: translated_verses translated_verses_project_unit_id_project_units_id_fk; Type: FK CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.translated_verses
    ADD CONSTRAINT translated_verses_project_unit_id_project_units_id_fk FOREIGN KEY (project_unit_id) REFERENCES public.project_units(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: user_chapter_assignment_editor_state user_chapter_assignment_editor_state_chapter_assignment_id_chap; Type: FK CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.user_chapter_assignment_editor_state
    ADD CONSTRAINT user_chapter_assignment_editor_state_chapter_assignment_id_chap FOREIGN KEY (chapter_assignment_id) REFERENCES public.chapter_assignments(id) ON DELETE CASCADE;


--
-- Name: user_chapter_assignment_editor_state user_chapter_assignment_editor_state_user_id_users_id_fk; Type: FK CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.user_chapter_assignment_editor_state
    ADD CONSTRAINT user_chapter_assignment_editor_state_user_id_users_id_fk FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: users users_created_by_users_id_fk; Type: FK CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_created_by_users_id_fk FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: users users_organization_organizations_id_fk; Type: FK CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_organization_organizations_id_fk FOREIGN KEY (organization) REFERENCES public.organizations(id);


--
-- Name: users users_role_roles_id_fk; Type: FK CONSTRAINT; Schema: public; Owner: scribedb_dev
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_role_roles_id_fk FOREIGN KEY (role) REFERENCES public.roles(id);


--
--



--
-- Name: TABLE active_chapter_editors; Type: ACL; Schema: public; Owner: scribedb_admin
--



--
-- Name: DEFAULT PRIVILEGES FOR SEQUENCES; Type: DEFAULT ACL; Schema: public; Owner: scribedb_admin
--



--
-- Name: DEFAULT PRIVILEGES FOR FUNCTIONS; Type: DEFAULT ACL; Schema: public; Owner: scribedb_admin
--



--
-- Name: DEFAULT PRIVILEGES FOR TABLES; Type: DEFAULT ACL; Schema: public; Owner: scribedb_admin
--



--
-- Name: DEFAULT PRIVILEGES FOR TABLES; Type: DEFAULT ACL; Schema: public; Owner: scribedb_dev
--



--
-- PostgreSQL database dump complete
--


