#define _GNU_SOURCE
#include <pappl/pappl.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <unistd.h>
#include <sys/wait.h>
#include <signal.h>
#include <time.h>

typedef struct { FILE *file; unsigned rows, pages; bool failed; char dir[256]; } job_data;
static bool start_job(pappl_job_t *j, pappl_pr_options_t *o, pappl_device_t *d) {
 (void)o;(void)d;
 job_data *s=calloc(1,sizeof(*s)); if(!s)return false;
 snprintf(s->dir,sizeof(s->dir),"/tmp/niimbot-job-XXXXXX");
 if(!mkdtemp(s->dir)){free(s);return false;}
 papplJobSetData(j,s);return true;
}
static bool start_page(pappl_job_t *j,pappl_pr_options_t *o,pappl_device_t *d,unsigned page) {
 (void)d;(void)page;job_data *s=papplJobGetData(j);
 if((o->header.cupsWidth<95 || o->header.cupsWidth>96) || (o->header.cupsHeight<319 || o->header.cupsHeight>320) || o->header.cupsBitsPerPixel!=1 || ++s->pages>100){s->failed=true;return false;}
 char name[300];snprintf(name,sizeof(name),"%s/%u.raw",s->dir,s->pages);
 s->file=fopen(name,"wb");s->rows=0;if(!s->file)s->failed=true;return s->file!=NULL;
}
static bool line(pappl_job_t *j,pappl_pr_options_t *o,pappl_device_t *d,unsigned y,const unsigned char *pixels) {
 (void)o;(void)d;job_data *s=papplJobGetData(j);
 if(papplJobIsCanceled(j)||!s->file||y!=s->rows){s->failed=true;return false;}
 unsigned char row[96];for(unsigned x=0;x<96;x++)row[x]=x>=o->header.cupsWidth?255:(pixels[x/8]&(128>>(x%8)))?0:255;
 if(fwrite(row,1,96,s->file)!=96){s->failed=true;return false;}s->rows++;return true;
}
static bool end_page(pappl_job_t *j,pappl_pr_options_t *o,pappl_device_t *d,unsigned page) {
 (void)o;(void)d;(void)page;job_data *s=papplJobGetData(j);
 if(s->file && s->rows==319){unsigned char white[96];memset(white,255,96);if(fwrite(white,1,96,s->file)==96)s->rows++;}
 bool ok=s->file && s->rows==320;
 if(s->file){if(fclose(s->file))ok=false;s->file=NULL;}s->failed|=!ok;return ok;
}
static bool end_job(pappl_job_t *j,pappl_pr_options_t *o,pappl_device_t *d) {
 (void)o;(void)d;job_data *s=papplJobGetData(j);
 if(!s)return false;
 bool ok=false;
 if(s && !s->failed && !papplJobIsCanceled(j)) {
  char copies[16];snprintf(copies,sizeof(copies),"1"); /* PAPPL images/CUPS raster already expand copies. */
  pid_t pid=fork();
  if(pid==0){execlp("python3","python3","ipp/supervise.py",s->dir,copies,(char*)NULL);_exit(127);}
  if(pid>0){int status=0;time_t until=time(NULL)+35+30*s->pages*o->copies;bool stopping=false;time_t stop_at=0;while(waitpid(pid,&status,WNOHANG)==0){if(!stopping&&(papplJobIsCanceled(j)||time(NULL)>=until)){kill(pid,SIGTERM);stopping=true;stop_at=time(NULL)+5;}if(stopping&&time(NULL)>=stop_at)kill(pid,SIGKILL);usleep(100000);}ok=WIFEXITED(status)&&WEXITSTATUS(status)==0;}
 }
 if(!ok){
 char error_path[300],message[512]="Job failed or cancelled; output may be partial. Check service log before explicitly resubmitting.";
 snprintf(error_path,sizeof(error_path),"%s/error.txt",s->dir);FILE *error=fopen(error_path,"r");if(error){if(!fgets(message,sizeof(message),error)){}fclose(error);unlink(error_path);}
 papplJobSetMessage(j,"%s",message);papplJobSetReasons(j,PAPPL_JREASON_ERRORS_DETECTED,PAPPL_JREASON_NONE);
 }
 if(s){if(s->file)fclose(s->file);for(unsigned p=1;p<=s->pages;p++){char n[300];snprintf(n,sizeof(n),"%s/%u.raw",s->dir,p);unlink(n);}char n[300];snprintf(n,sizeof(n),"%s/manifest.json",s->dir);unlink(n);rmdir(s->dir);free(s);papplJobSetData(j,NULL);}return ok;
}

static bool driver(pappl_system_t *sys,const char *name,const char *uri,const char *id,pappl_pr_driver_data_t *v,ipp_t **attrs,void *data) {
 (void)sys;(void)name;(void)uri;(void)id;(void)attrs;(void)data;
 snprintf(v->make_and_model,sizeof(v->make_and_model),"Niimbot D110M");
 v->rstartjob_cb=start_job;v->rstartpage_cb=start_page;v->rwriteline_cb=line;v->rendpage_cb=end_page;v->rendjob_cb=end_job;
 v->ppm=10;v->format="application/x-niimbot-disabled";
 v->num_resolution=1;v->x_resolution[0]=v->y_resolution[0]=v->x_default=v->y_default=203;
 v->raster_types=v->force_raster_type=PAPPL_PWG_RASTER_TYPE_BLACK_1;
 v->color_supported=PAPPL_COLOR_MODE_BI_LEVEL|PAPPL_COLOR_MODE_MONOCHROME;v->color_default=PAPPL_COLOR_MODE_MONOCHROME;
 v->sides_supported=v->sides_default=PAPPL_SIDES_ONE_SIDED;
 v->num_media=1;v->media[0]="custom_12x40mm_12x40mm";
 v->media_default.size_width=1200;v->media_default.size_length=4000;strcpy(v->media_default.size_name,v->media[0]);strcpy(v->media_default.source,"roll-1");strcpy(v->media_default.type,"labels");v->media_ready[0]=v->media_default;
 v->num_source=1;v->source[0]="roll-1";v->num_type=1;v->type[0]="labels";
 return true;
}
static bool device_open(pappl_device_t *d,const char *u,const char *n){(void)d;(void)u;(void)n;return true;}
static void device_close(pappl_device_t *d){(void)d;}
int main(void) {
 pappl_pr_driver_t drivers[]={{"niimbot-d110m","Niimbot D110M 12x40 mm",NULL,NULL}};
 const char *spool=getenv("NIIMBOT_SPOOL");if(!spool){fprintf(stderr,"Set NIIMBOT_SPOOL to a private directory\n");return 1;}
 papplDeviceAddScheme("niimbot",PAPPL_DEVTYPE_CUSTOM_LOCAL,NULL,device_open,device_close,NULL,NULL,NULL,NULL);
 pappl_system_t *s=papplSystemCreate(PAPPL_SOPTIONS_NO_TLS,"Niimbot",getenv("NIIMBOT_PORT")?atoi(getenv("NIIMBOT_PORT")):8631,NULL,spool,"-",PAPPL_LOGLEVEL_DEBUG,NULL,false);
 if(!s)return 1;
 papplSystemSetHostName(s,"localhost");
 papplSystemSetPrinterDrivers(s,1,drivers,NULL,NULL,driver,NULL);
 if(!papplSystemAddListeners(s,"127.0.0.1"))return 1;
 pappl_printer_t *p=papplPrinterCreate(s,1,"Niimbot D110M", "niimbot-d110m",NULL,"niimbot://configured");
 if(!p)return 1;
 papplPrinterSetDNSSDName(p,NULL);papplSystemSetDNSSDName(s,NULL);
 papplSystemRun(s);papplSystemDelete(s);return 0;
}
